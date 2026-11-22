"""Chargement Postgres des données fraîches (Jikan, AniList) dans le schéma catalog.

Règles :
- une transaction par chargement (rien de partiel visible par l'API ou Power BI) ;
- upserts idempotents : relancer un DAG pour la même date ne crée aucun doublon ;
- les lignes du dataset 2020 (data_source = 'mal_kaggle_2020') servent de features au modèle de
  drop : Jikan n'y complète QUE la couverture et le statut de diffusion, jamais les colonnes
  utilisées comme features (format, épisodes, studios…) ;
- aucune œuvre n'est supprimée : les listes des utilisateurs (phase 7) pointeront dessus.
"""

import datetime as dt
import logging
from collections.abc import Sequence

import psycopg
from psycopg import sql

from tsuzuku_pipeline.db.loader import KAGGLE_SOURCE, _copy
from tsuzuku_pipeline.ingestion.records import MediaRecord, StatsRecord

logger = logging.getLogger("tsuzuku_pipeline.ingestion")

JIKAN_SOURCE, ANILIST_SOURCE = "jikan", "anilist"

# Colonnes de catalog.media remplies par l'ingestion (ordre = ordre du COPY).
COLUMNS = (
    "kind", "mal_id", "anilist_id", "title", "title_alt", "synopsis", "episodes", "chapters",
    "airing_status", "format", "duration_min", "start_year", "creators", "source", "age_rating",
    "cover_url", "cover_color", "cover_source", "popularity",
)  # fmt: skip
COVER_COLUMNS = ("cover_url", "cover_color", "cover_source")


def _row(r: MediaRecord) -> tuple:
    return (r.kind, r.mal_id, r.anilist_id, r.title, r.title_alt, r.synopsis, r.episodes,
            r.chapters, r.airing_status, r.format, r.duration_min, r.start_year,
            list(r.creators), r.source, r.age_rating, r.cover_url, r.cover_color, r.cover_source,
            r.popularity)  # fmt: skip


def _ids(cols: Sequence[str]) -> sql.Composed:
    """Liste de colonnes en identifiants SQL échappés (jamais de SQL construit par f-string)."""
    return sql.SQL(", ").join(map(sql.Identifier, cols))


def _assign(cols: Sequence[str], source: str) -> sql.Composed:
    """« col = source.col, … » ; source vaut 't' (table de travail) ou 'EXCLUDED' (upsert)."""
    return sql.SQL(", ").join(
        sql.SQL("{c} = {s}.{c}").format(c=sql.Identifier(c), s=sql.SQL(source)) for c in cols
    )


def _keep_approved_cover(target: str, source: str) -> sql.Composed:
    """« cover_* = … » qui ne remplace JAMAIS une jaquette proposée par un utilisateur et validée
    par Royston (cover_source = 'suggestion') : une synchro ne défait pas une modération."""
    return sql.SQL(", ").join(
        sql.SQL(
            "{c} = CASE WHEN {t}.cover_source = 'suggestion' THEN {t}.{c} ELSE {s}.{c} END"
        ).format(c=sql.Identifier(c), t=sql.SQL(target), s=sql.SQL(source))
        for c in COVER_COLUMNS
    )


def _stage_media(conn: psycopg.Connection, records: Sequence[MediaRecord]) -> None:
    conn.execute(sql.SQL("CREATE TEMP TABLE tmp_ing ON COMMIT DROP AS SELECT {} FROM catalog.media"
                         " WITH NO DATA").format(_ids(COLUMNS)))  # fmt: skip
    _copy(conn, "tmp_ing", COLUMNS, (_row(r) for r in records))


# Clé de rattachement des genres/tags selon la source (liste blanche).
_MATCH = {
    "mal_id": sql.SQL("m.mal_id = t.k AND m.kind = 'anime'"),
    "anilist_id": sql.SQL("m.anilist_id = t.k"),
}
_SCOPE = {
    "mal_id": sql.SQL("m.kind = 'anime' AND m.mal_id IN (SELECT mal_id FROM tmp_ing)"),
    "anilist_id": sql.SQL("m.anilist_id IN (SELECT anilist_id FROM tmp_ing)"),
}


def _replace_labels(conn: psycopg.Connection, records: Sequence[MediaRecord], key: str,
                    source: str) -> None:  # fmt: skip
    """Remplace genres et tags des œuvres de CETTE source présentes dans le lot."""
    match, scope = _MATCH[key], _SCOPE[key]
    conn.execute("CREATE TEMP TABLE tmp_genre (k bigint, name text) ON COMMIT DROP")
    conn.execute("CREATE TEMP TABLE tmp_tag (k bigint, name text, rank smallint) ON COMMIT DROP")
    _copy(conn, "tmp_genre", ("k", "name"),
          ((getattr(r, key), g) for r in records for g in r.genres))  # fmt: skip
    _copy(conn, "tmp_tag", ("k", "name", "rank"),
          ((getattr(r, key), n, rank) for r in records for n, rank in r.tags))  # fmt: skip
    conn.execute("INSERT INTO catalog.genre (name) SELECT DISTINCT name FROM tmp_genre"
                 " ON CONFLICT (name) DO NOTHING")  # fmt: skip
    conn.execute("INSERT INTO catalog.tag (name) SELECT DISTINCT name FROM tmp_tag"
                 " ON CONFLICT (name) DO NOTHING")  # fmt: skip
    for table in ("media_genre", "media_tag"):
        delete = sql.SQL(
            "DELETE FROM catalog.{} x USING catalog.media m"
            " WHERE x.media_id = m.id AND m.data_source = %s AND {}"
        ).format(sql.Identifier(table), scope)
        conn.execute(delete, (source,))
    conn.execute(sql.SQL(
        "INSERT INTO catalog.media_genre (media_id, genre_id) SELECT DISTINCT m.id, g.id"
        " FROM tmp_genre t JOIN catalog.media m ON {} JOIN catalog.genre g ON g.name = t.name"
        " WHERE m.data_source = %s ON CONFLICT DO NOTHING").format(match), (source,))  # fmt: skip
    conn.execute(sql.SQL(
        "INSERT INTO catalog.media_tag (media_id, tag_id, rank) SELECT m.id, g.id, max(t.rank)"
        " FROM tmp_tag t JOIN catalog.media m ON {} JOIN catalog.tag g ON g.name = t.name"
        " WHERE m.data_source = %s GROUP BY m.id, g.id ON CONFLICT DO NOTHING").format(match),
        (source,))  # fmt: skip
    conn.execute("DROP TABLE tmp_genre, tmp_tag")


def upsert_jikan_anime(conn: psycopg.Connection, records: Sequence[MediaRecord]) -> dict[int, int]:
    """Animes vus par Jikan → {mal_id: media_id}.

    - absent du catalogue : inséré (data_source = 'jikan') ;
    - déjà inséré par Jikan : fiche mise à jour ;
    - venu du dataset 2020 : seuls cover_url (absente du dataset) et airing_status sont complétés.
    """
    records = list({r.mal_id: r for r in records if r.mal_id is not None}.values())
    with conn.transaction():
        _stage_media(conn, records)
        conn.execute(sql.SQL(
            "INSERT INTO catalog.media ({c}, data_source) SELECT {c}, %s FROM tmp_ing"
            " ON CONFLICT ON CONSTRAINT media_kind_mal_id_key DO NOTHING").format(c=_ids(COLUMNS)),
            (JIKAN_SOURCE,))  # fmt: skip
        updatable = [c for c in COLUMNS
                     if c not in ("kind", "mal_id", "anilist_id", *COVER_COLUMNS)]  # fmt: skip
        conn.execute(sql.SQL(
            "UPDATE catalog.media m SET {}, updated_at = now() FROM tmp_ing t"
            " WHERE m.kind = 'anime' AND m.mal_id = t.mal_id AND m.data_source = %s"
        ).format(_assign(updatable, "t")), (JIKAN_SOURCE,))  # fmt: skip
        # Jaquette (animes de Jikan comme du dataset 2020) : Jikan ne fait que COMPLÉTER une
        # jaquette absente. Il ne remplace ni une image AniList (plus grande), ni une jaquette
        # validée, et ne l'efface pas quand il n'en envoie pas (elle clignotait d'un jour à
        # l'autre, revue du lot qualité).
        conn.execute(
            "UPDATE catalog.media m SET cover_url = COALESCE(m.cover_url, t.cover_url),"
            " cover_source = CASE WHEN m.cover_url IS NULL AND t.cover_url IS NOT NULL"
            " THEN 'jikan' ELSE m.cover_source END, updated_at = now()"
            " FROM tmp_ing t WHERE m.kind = 'anime' AND m.mal_id = t.mal_id"
            " AND m.data_source IN (%s, %s)",
            (KAGGLE_SOURCE, JIKAN_SOURCE),
        )
        conn.execute(
            "UPDATE catalog.media m SET"
            " airing_status = COALESCE(t.airing_status, m.airing_status), updated_at = now()"
            " FROM tmp_ing t WHERE m.kind = 'anime' AND m.mal_id = t.mal_id"
            " AND m.data_source = %s",
            (KAGGLE_SOURCE,),
        )
        _replace_labels(conn, records, "mal_id", JIKAN_SOURCE)
        ids = dict(conn.execute(
            "SELECT m.mal_id, m.id FROM catalog.media m JOIN tmp_ing t"
            " ON m.kind = 'anime' AND m.mal_id = t.mal_id"
        ).fetchall())  # fmt: skip
        conn.execute("DROP TABLE tmp_ing")
    logger.info("catalog.media : %d animes Jikan traités", len(ids))
    return ids


STATS_COLUMNS = ("snapshot_date", "media_id", "score", "members", "watching", "completed",
                 "on_hold", "dropped", "plan_to_watch", "source", "in_season")  # fmt: skip


def upsert_daily_stats(
    conn: psycopg.Connection, day: dt.date, stats: Sequence[StatsRecord], ids: dict[int, int],
    source: str = JIKAN_SOURCE,
) -> int:  # fmt: skip
    """Statistiques du jour, upsert sur (snapshot_date, media_id) : idempotent."""
    rows = [
        (day, ids[s.mal_id], s.score, s.members, s.watching, s.completed, s.on_hold, s.dropped,
         s.plan_to_watch, source, s.in_season)
        for s in stats if s.mal_id in ids
    ]  # fmt: skip
    cols = _ids(STATS_COLUMNS)
    with conn.transaction():
        stage = sql.SQL(
            "CREATE TEMP TABLE tmp_stats ON COMMIT DROP AS SELECT {}"
            " FROM catalog.media_daily_stats WITH NO DATA"
        ).format(cols)
        conn.execute(stage)
        _copy(conn, "tmp_stats", STATS_COLUMNS, rows)
        conn.execute(sql.SQL(
            "INSERT INTO catalog.media_daily_stats ({c}) SELECT {c} FROM tmp_stats"
            " ON CONFLICT (snapshot_date, media_id) DO UPDATE SET {u}, fetched_at = now()"
        ).format(c=cols, u=_assign(STATS_COLUMNS[2:], "EXCLUDED")))  # fmt: skip
        conn.execute("DROP TABLE tmp_stats")
    return len(rows)


# Seules les images du CDN d'AniList sont acceptées : l'URL est affichée telle quelle par le front
# (et autorisée dans sa politique de sécurité du contenu), elle ne doit pas pointer n'importe où.
# Même chemin que les remotePatterns du front (frontend/next.config.ts) : une URL acceptée ici
# est toujours affichable là-bas.
COVER_URL_PREFIX = "https://s4.anilist.co/file/anilistcdn/"


def is_trusted_cover(url: object) -> bool:
    """URL du CDN d'AniList, et pas son image par défaut (« default.jpg »)."""
    return (isinstance(url, str) and url.startswith(COVER_URL_PREFIX)
            and not url.rsplit("/", 1)[-1].startswith("default."))  # fmt: skip


def anime_cover_targets(conn: psycopg.Connection) -> list[int]:
    """idMal des animes à (re)demander à AniList, les plus populaires d'abord :
    - sans jaquette ;
    - avec une PETITE image AniList (chemin /cover/medium/, 230 px) : la grande existe (460 px).
    Jamais une image MyAnimeList (Jikan) ni une jaquette validée par Royston. Un titre pour
    lequel AniList n'a pas de grande image reste demandé à chaque passage (cas non observé sur
    l'échantillon du 2026-11-22 ; coût : une place dans un lot de 50)."""
    rows = conn.execute(
        "SELECT mal_id FROM catalog.media WHERE kind = 'anime' AND mal_id IS NOT NULL"
        " AND (cover_url IS NULL OR (cover_source = 'anilist' AND cover_url LIKE %s))"
        " ORDER BY popularity NULLS LAST, mal_id",
        (COVER_URL_PREFIX + "%/cover/medium/%",),
    ).fetchall()
    return [r[0] for r in rows]


def missing_anime_count(conn: psycopg.Connection) -> int:
    """Animes sans jaquette qu'AniList pourrait remplir (avec un idMal)."""
    return conn.execute(
        "SELECT count(*) FROM catalog.media WHERE kind = 'anime' AND mal_id IS NOT NULL"
        " AND cover_url IS NULL"
    ).fetchone()[0]


def apply_anime_covers(conn: psycopg.Connection, covers: dict[int, dict[str, str | None]]) -> int:
    """Jaquettes AniList des animes ({idMal: {url, color}}) : remplit les absentes et remplace
    les petites images AniList. Seuls les champs de jaquette sont touchés (lignes du dataset 2020
    protégées, ADR 007) ; jamais une image MyAnimeList ni une jaquette validée par Royston."""
    rows = [(mal, c["url"], c.get("color")) for mal, c in covers.items()
            if isinstance(c, dict) and is_trusted_cover(c.get("url"))]  # fmt: skip
    if not rows:
        return 0
    with conn.transaction():
        conn.execute("CREATE TEMP TABLE tmp_cover (mal_id integer, url text, color text)"
                     " ON COMMIT DROP")  # fmt: skip
        with conn.cursor().copy("COPY tmp_cover (mal_id, url, color) FROM STDIN") as copy:
            for row in rows:
                copy.write_row(row)
        updated = conn.execute(
            "UPDATE catalog.media m SET cover_url = t.url, cover_color = t.color,"
            " cover_source = 'anilist', updated_at = now() FROM tmp_cover t"
            " WHERE m.kind = 'anime' AND m.mal_id = t.mal_id"
            " AND (m.cover_url IS NULL OR (m.cover_source = 'anilist' AND m.cover_url <> t.url))"
        ).rowcount
    logger.info("catalog.media : %d jaquette(s) d'anime ajoutée(s) ou agrandie(s)", updated)
    return updated


def upsert_anilist_media(
    conn: psycopg.Connection, records: Sequence[MediaRecord]
) -> dict[str, int]:
    """Titres AniList (clé : anilist_id). Renvoie des compteurs pour le rapport.

    Un idMal déjà porté par une autre œuvre du même type (contrainte unique kind + mal_id) est mis
    à null pour ce titre plutôt que de faire échouer tout le chargement ; c'est compté.
    """
    received = len(records)
    # Un titre peut apparaître sur deux pages si le classement bouge pendant la récupération.
    records = list({r.anilist_id: r for r in records if r.anilist_id is not None}.values())
    with conn.transaction():
        _stage_media(conn, records)
        # Doublons d'idMal dans le lot (même type) : on garde le plus populaire (rang le plus bas).
        dup_batch = conn.execute(
            "UPDATE tmp_ing t SET mal_id = NULL WHERE t.mal_id IS NOT NULL AND EXISTS ("
            " SELECT 1 FROM tmp_ing o WHERE o.kind = t.kind AND o.mal_id = t.mal_id"
            " AND (o.popularity < t.popularity OR (o.popularity = t.popularity"
            " AND o.anilist_id < t.anilist_id)))"
        ).rowcount
        dup_db = conn.execute(
            "UPDATE tmp_ing t SET mal_id = NULL WHERE t.mal_id IS NOT NULL AND EXISTS ("
            " SELECT 1 FROM catalog.media m WHERE m.kind = t.kind AND m.mal_id = t.mal_id"
            " AND m.anilist_id IS DISTINCT FROM t.anilist_id)"
        ).rowcount
        updatable = [c for c in COLUMNS if c != "anilist_id" and c not in COVER_COLUMNS]
        inserted = conn.execute(sql.SQL(
            "INSERT INTO catalog.media ({c}, data_source) SELECT {c}, %s FROM tmp_ing"
            " ON CONFLICT (anilist_id) DO UPDATE SET {u}, {k}, updated_at = now()"
            " RETURNING (xmax = 0)"
        ).format(c=_ids(COLUMNS), u=_assign(updatable, "EXCLUDED"),
                 k=_keep_approved_cover("media", "EXCLUDED")),
            (ANILIST_SOURCE,)).fetchall()  # fmt: skip
        _replace_labels(conn, records, "anilist_id", ANILIST_SOURCE)
        # Titre sorti du top récupéré : son ancien rang n'a plus de sens (deux titres finiraient
        # avec le même). Rang inconnu (NULL) plutôt que faux ; l'œuvre n'est pas supprimée.
        stale_rank = conn.execute(
            "UPDATE catalog.media m SET popularity = NULL, updated_at = now()"
            " WHERE m.data_source = %s AND m.popularity IS NOT NULL"
            " AND NOT EXISTS (SELECT 1 FROM tmp_ing t WHERE t.anilist_id = m.anilist_id)",
            (ANILIST_SOURCE,),
        ).rowcount
        conn.execute("DROP TABLE tmp_ing")
    # xmax = 0 : ligne réellement insérée (et non mise à jour par le ON CONFLICT).
    new = sum(1 for (is_new,) in inserted if is_new)
    counts = {"loaded": len(inserted), "inserted": new, "updated": len(inserted) - new,
              "duplicates": received - len(records),
              "mal_id_cleared": dup_batch + dup_db, "rank_cleared": stale_rank}  # fmt: skip
    logger.info("catalog.media AniList : %s", counts)
    return counts
