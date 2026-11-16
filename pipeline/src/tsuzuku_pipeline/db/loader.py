"""Chargement Postgres du catalogue anime et des marts (ADR 003).

Principes :
- COPY plutôt que des INSERT ligne à ligne : un seul flux réseau, des centaines de milliers de
  lignes en quelques secondes ;
- chaque chargement tient dans UNE transaction : en cas d'erreur, rien n'est modifié, et un
  lecteur (API, Power BI) ne voit jamais une table à moitié remplie ;
- catalog.media est mis à jour par upsert (ids stables), les marts sont remplacés en entier ;
- l'URL de connexion n'apparaît jamais dans les logs ni les erreurs (elle contient le mot de passe).
"""

import logging
import os
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

import psycopg
from dotenv import load_dotenv
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict
from psycopg.types.json import Jsonb

from tsuzuku_pipeline.config import REPO_ROOT
from tsuzuku_pipeline.spark.build_catalog import MEDIA_COLUMNS

logger = logging.getLogger(__name__)

SCHEMA_FILES = (
    Path(__file__).with_name("schema_catalog.sql"),
    Path(__file__).with_name("schema_mart.sql"),
)

# Marts connus : colonnes dans l'ordre des lignes fournies, et clé de rattachement au catalogue.
# Liste blanche : les noms de tables ne viennent jamais d'une entrée extérieure.
MARTS: dict[str, dict[str, Any]] = {
    "drop_curve": {
        "columns": ("episode", "nb_drops", "cumulative_share"),
        "by_media": True,
    },
    "critical_episode": {
        "columns": (
            "critical_episode",
            "critical_drop_share",
            "initial_drop_risk",
            "point_of_no_return",
            "nb_drops",
            "nb_completed",
            "drop_rate",
        ),
        "by_media": True,
    },
    "retention_by_genre": {
        "columns": (
            "genre",
            "nb_anime",
            "nb_completed",
            "nb_dropped",
            "drop_rate",
            "completion_rate",
            "median_drop_progress",
        ),
        "by_media": False,
    },
    "retention_by_studio": {
        "columns": (
            "studio",
            "nb_anime",
            "nb_completed",
            "nb_dropped",
            "drop_rate",
            "completion_rate",
            "median_drop_progress",
        ),
        "by_media": False,
    },
}


class LoaderError(Exception):
    """Chargement impossible ou incohérent (rien n'a été écrit)."""


def database_url() -> str:
    # .env n'est pas chargé automatiquement par Python : on le lit sans écraser une variable déjà
    # définie (en CI, DATABASE_URL vient de l'environnement du job).
    load_dotenv(REPO_ROOT / ".env", override=False)
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise LoaderError("DATABASE_URL absent : copie .env.example en .env (make setup)")
    return url


def describe(url: str) -> str:
    """hôte:port/base, sans identifiants : seule forme de l'URL autorisée dans les logs."""
    try:
        info = conninfo_to_dict(url)
    except psycopg.Error:
        # Le message d'erreur de libpq recopie la chaîne de connexion, mot de passe compris.
        return "<DATABASE_URL invalide>"
    return f"{info.get('host', 'localhost')}:{info.get('port', '5432')}/{info.get('dbname', '')}"


def connect(url: str) -> psycopg.Connection:
    try:
        return psycopg.connect(url, connect_timeout=10)
    except psycopg.Error as exc:
        # psycopg.Error et pas seulement OperationalError : une URL mal formée lève une
        # ProgrammingError dont le message contient l'URL. `from None` coupe la chaîne d'erreurs.
        logger.error("Connexion Postgres impossible (%s)", type(exc).__name__)
        raise LoaderError(
            f"Connexion impossible à {describe(url)} ({type(exc).__name__}) : "
            "Postgres est-il démarré (make up) et DATABASE_URL est-elle valide ?"
        ) from None


def apply_schemas(conn: psycopg.Connection, lock_timeout: str = "30s") -> None:
    """Crée schémas, tables et index s'ils manquent (DDL idempotent)."""
    with conn.transaction():
        _set_lock_timeout(conn, lock_timeout)
        for path in SCHEMA_FILES:
            conn.execute(path.read_text(encoding="utf-8"))


def _set_lock_timeout(conn: psycopg.Connection, value: str) -> None:
    # SET LOCAL : le réglage s'arrête avec la transaction, la connexion n'est pas modifiée.
    conn.execute(sql.SQL("SET LOCAL lock_timeout = {}").format(sql.Literal(value)))


def _copy(conn: psycopg.Connection, table: str | sql.Composable, columns: Sequence[str],
          rows: Iterable) -> int:  # fmt: skip
    """COPY ligne par ligne depuis un itérable : rien n'est chargé en entier en mémoire."""
    target = sql.Identifier(table) if isinstance(table, str) else table
    query = sql.SQL("COPY {} ({}) FROM STDIN").format(
        target, sql.SQL(", ").join(map(sql.Identifier, columns))
    )
    n = 0
    with conn.cursor().copy(query) as copy:
        for row in rows:
            copy.write_row(row)
            n += 1
    return n


KAGGLE_SOURCE = "mal_kaggle_2020"


def upsert_media(
    conn: psycopg.Connection,
    media: Iterable[Sequence],
    genres: Iterable[tuple[int, str]],
    kind: str = "anime",
    data_source: str = KAGGLE_SOURCE,
) -> int:
    """Insère ou met à jour les œuvres (clé : kind + mal_id), remplace leurs genres, et retire
    celles de cette source qui n'y figurent plus.

    Upsert et non remplacement : l'`id` d'une œuvre doit rester le même d'un chargement à l'autre,
    car les listes des utilisateurs (phase 7) pointeront dessus.
    Retrait : une œuvre sortie de la couche clean (ex. nouvellement classée adulte) ne doit pas
    rester visible. On ne retire que les lignes de la MÊME source : celles ajoutées plus tard par
    Jikan ou AniList ne sont pas concernées.
    """
    cols = sql.SQL(", ").join(map(sql.Identifier, MEDIA_COLUMNS))
    updates = sql.SQL(", ").join(
        sql.SQL("{c} = EXCLUDED.{c}").format(c=sql.Identifier(c))
        for c in MEDIA_COLUMNS
        if c not in ("kind", "mal_id")
    )
    with conn.transaction():
        # Tables temporaires aux mêmes types que les vraies. Supprimées explicitement à la fin :
        # dans une transaction englobante, ON COMMIT DROP ne suffirait pas entre deux appels.
        conn.execute(
            sql.SQL(
                "CREATE TEMP TABLE tmp_media ON COMMIT DROP AS"
                " SELECT {} FROM catalog.media WITH NO DATA"
            ).format(cols)
        )
        n = _copy(conn, "tmp_media", MEDIA_COLUMNS, media)
        conn.execute(
            sql.SQL(
                "INSERT INTO catalog.media ({cols}, data_source)"
                " SELECT {cols}, %s FROM tmp_media"
                " ON CONFLICT ON CONSTRAINT media_kind_mal_id_key"
                " DO UPDATE SET {updates}, updated_at = now()"
            ).format(cols=cols, updates=updates),
            (data_source,),
        )
        removed = conn.execute(
            "DELETE FROM catalog.media m WHERE m.kind = %s AND m.data_source = %s"
            " AND NOT EXISTS (SELECT 1 FROM tmp_media t WHERE t.mal_id = m.mal_id)",
            (kind, data_source),
        ).rowcount
        if removed:
            logger.warning("catalog.media : %d œuvre(s) retirée(s), absentes de la source", removed)

        conn.execute(
            "CREATE TEMP TABLE tmp_media_genre (mal_id integer, genre text) ON COMMIT DROP"
        )
        _copy(conn, "tmp_media_genre", ("mal_id", "genre"), genres)
        conn.execute(
            "INSERT INTO catalog.genre (name) SELECT DISTINCT genre FROM tmp_media_genre"
            " ON CONFLICT (name) DO NOTHING"
        )
        # Les genres des œuvres chargées sont remplacés (pas accumulés d'un run à l'autre).
        conn.execute(
            "DELETE FROM catalog.media_genre mg USING catalog.media m"
            " WHERE mg.media_id = m.id AND m.kind = %s"
            " AND m.mal_id IN (SELECT mal_id FROM tmp_media)",
            (kind,),
        )
        conn.execute(
            "INSERT INTO catalog.media_genre (media_id, genre_id)"
            " SELECT DISTINCT m.id, g.id FROM tmp_media_genre t"
            " JOIN catalog.media m ON m.kind = %s AND m.mal_id = t.mal_id"
            " JOIN catalog.genre g ON g.name = t.genre",
            (kind,),
        )
        conn.execute("DROP TABLE tmp_media, tmp_media_genre")
    logger.info("catalog.media : %d œuvres (%s) chargées", n, kind)
    return n


def replace_mart(
    conn: psycopg.Connection,
    name: str,
    rows: Iterable[Sequence],
    kind: str = "anime",
    lock_timeout: str = "30s",
) -> int:
    """Remplace entièrement mart.<name> par `rows`, dans une transaction.

    Pour les marts par œuvre, la 1re valeur de chaque ligne est le mal_id : il est traduit en
    media_id via catalog.media. Un mal_id inconnu du catalogue annule tout (incohérence).

    lock_timeout : TRUNCATE attend que plus aucune transaction ne lise la table. Une session restée
    ouverte (rapport Power BI, console psql) bloquerait le chargement indéfiniment ; on préfère
    échouer clairement au bout de 30 s.
    """
    if name not in MARTS:
        raise LoaderError(f"Table de mart inconnue : {name!r}")
    try:
        return _replace_mart(conn, name, rows, kind, lock_timeout)
    except psycopg.errors.LockNotAvailable:
        raise LoaderError(
            f"mart.{name} verrouillée par une autre session depuis plus de {lock_timeout} "
            "(requête ou outil resté ouvert ?) ; chargement annulé"
        ) from None


def _replace_mart(
    conn: psycopg.Connection, name: str, rows: Iterable[Sequence], kind: str, lock_timeout: str
) -> int:
    spec = MARTS[name]
    columns = spec["columns"]
    target = sql.Identifier("mart", name)
    col_list = sql.SQL(", ").join(map(sql.Identifier, columns))

    with conn.transaction():
        _set_lock_timeout(conn, lock_timeout)
        if spec["by_media"]:
            conn.execute(
                sql.SQL(
                    "CREATE TEMP TABLE tmp_mart ON COMMIT DROP AS"
                    " SELECT NULL::integer AS mal_id, {} FROM {} WITH NO DATA"
                ).format(col_list, target)
            )
            n = _copy(conn, "tmp_mart", ("mal_id", *columns), rows)
            missing = conn.execute(
                "SELECT count(*), min(t.mal_id) FROM tmp_mart t"
                " LEFT JOIN catalog.media m ON m.kind = %s AND m.mal_id = t.mal_id"
                " WHERE m.id IS NULL",
                (kind,),
            ).fetchone()
            if missing[0]:
                raise LoaderError(
                    f"mart.{name} : {missing[0]} ligne(s) dont l'œuvre est absente du catalogue"
                    f" (ex. mal_id {missing[1]}) ; chargement annulé"
                )
            # TRUNCATE dans la transaction : les lecteurs voient l'ancienne version jusqu'au COMMIT.
            conn.execute(sql.SQL("TRUNCATE {}").format(target))
            conn.execute(
                sql.SQL(
                    "INSERT INTO {} (media_id, {cols}) SELECT m.id, {tcols} FROM tmp_mart t"
                    " JOIN catalog.media m ON m.kind = %s AND m.mal_id = t.mal_id"
                ).format(
                    target,
                    cols=col_list,
                    tcols=sql.SQL(", ").join(sql.Identifier("t", c) for c in columns),
                ),
                (kind,),
            )
            # Explicite : le mart suivant recrée tmp_mart dans la même transaction englobante.
            conn.execute("DROP TABLE tmp_mart")
        else:
            conn.execute(sql.SQL("TRUNCATE {}").format(target))
            n = _copy(conn, target, columns, rows)
    logger.info("mart.%s : %d lignes chargées", name, n)
    return n


MODEL_RUN_FIELDS = (
    "run_id",
    "created_at",
    "model_name",
    "model_type",
    "params",
    "metrics",
    "data_fingerprint",
    "artifact",
)


def insert_model_run(conn: psycopg.Connection, run: dict[str, Any]) -> bool:
    """Enregistre un entraînement dans mart.model_runs (ajout seul).

    Idempotent par run_id : réenregistrer le même run (ex. `make train` relancé sans réentraîner)
    ne crée pas de doublon. Renvoie True si une ligne a été ajoutée.
    """
    missing = [f for f in MODEL_RUN_FIELDS if f not in run]
    if missing:
        raise LoaderError(f"model_run incomplet : {', '.join(missing)}")
    with conn.transaction():
        cur = conn.execute(
            "INSERT INTO mart.model_runs"
            " (run_id, created_at, model_name, model_type, params, metrics, data_fingerprint,"
            " artifact) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)"
            " ON CONFLICT (run_id) DO NOTHING",
            (
                run["run_id"],
                run["created_at"],
                run["model_name"],
                run["model_type"],
                Jsonb(run["params"]),
                Jsonb(run["metrics"]),
                run["data_fingerprint"],
                run["artifact"],
            ),
        )
    added = cur.rowcount == 1
    logger.info("mart.model_runs : run %s %s", run["run_id"], "ajouté" if added else "déjà présent")
    return added
