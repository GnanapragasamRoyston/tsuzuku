"""API de test pour les tests de bout en bout du front (Playwright, phase 8).

Prépare une base DÉDIÉE (tsuzuku_e2e, recréée à chaque lancement), puis lance l'API sur le port
8001 :
- schémas catalog/mart du pipeline + migrations Alembic du schéma app (comme en vrai) ;
- mini catalogue : 16 animes fictifs en deux groupes de goûts, 3 mangas ;
- mini modèles de reco et de drop (mêmes helpers que les tests backend) ;
- réglages = config/settings.yaml, avec des limites de débit larges : tous les tests passent
  par la même IP (le relais Next), la limite de 5 inscriptions par heure bloquerait la suite.

Lancement : `uv run python scripts/e2e_api.py` (depuis backend/), ou par Playwright (webServer).
N'utilise jamais la base de dev : seulement la base tsuzuku_e2e, sur le même serveur.
"""

import secrets
import sys
from pathlib import Path

import httpx
import psycopg
import uvicorn
import yaml
from alembic import command
from psycopg import sql
from sqlalchemy.engine import make_url

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))  # pour réutiliser les helpers de tests/conftest.py

import numpy as np  # noqa: E402
from tests.conftest import (  # noqa: E402
    GENRES,
    SCHEMA_DIR,
    _base_url,
    alembic_config,
    write_drop,
    write_reco,
)
from tsuzuku_ml.fold_in import FoldInModel  # noqa: E402

from app.core.config import REPO_ROOT, Settings, load_rules  # noqa: E402
from app.main import create_app  # noqa: E402

DB_NAME = "tsuzuku_e2e"
OUT = REPO_ROOT / "data" / "e2e"
PORT = 8001
N_ANIME = 16
EMBEDDING_DIM = 384  # même dimension que catalog.media_embedding (phase 10)


def create_database() -> str:
    base = _base_url()
    with psycopg.connect(base, autocommit=True, connect_timeout=3) as admin:
        admin.execute(
            sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(DB_NAME))
        )
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(DB_NAME)))
    url = make_url(base).set(database=DB_NAME).render_as_string(hide_password=False)
    with psycopg.connect(url, autocommit=True) as conn:
        for f in ("schema_catalog.sql", "schema_mart.sql"):
            conn.execute((SCHEMA_DIR / f).read_text(encoding="utf-8"))
    command.upgrade(alembic_config(url), "head")
    return url


E2E_CURVE = ((1, 5), (2, 2), (4, 2), (6, 1))


def seed_catalog(url: str) -> None:
    """Animes 1-8 : groupe « action », 9-16 : groupe « drame ». Titres volontairement fictifs."""
    with psycopg.connect(url, autocommit=True) as conn:
        genre = {g: conn.execute("INSERT INTO catalog.genre (name) VALUES (%s) RETURNING id",
                                 (g,)).fetchone()[0] for g in GENRES}  # fmt: skip
        for mal in range(1, N_ANIME + 1):
            mid = conn.execute(
                "INSERT INTO catalog.media (kind, mal_id, title, format, episodes, start_year,"
                " popularity, creators, source, age_rating, duration_min, data_source)"
                " VALUES ('anime', %s, %s, 'TV', 12, 2010, %s, '{Studio}', 'Manga', 'PG-13', 24,"
                " 'mal_kaggle_2020') RETURNING id",
                (mal, f"Anime de test {mal:02d}", mal),
            ).fetchone()[0]
            g = "Action" if mal <= N_ANIME // 2 else "Drama"
            conn.execute("INSERT INTO catalog.media_genre VALUES (%s, %s)", (mid, genre[g]))
            # Courbe de drop FICTIVE (fiche œuvre, phase 9) : 10 drops, pic à l'épisode 1,
            # point de non-retour à l'épisode 4. Base E2E seulement, jamais montrée comme réelle.
            cumulative = 0
            for episode, drops in E2E_CURVE:
                cumulative += drops
                conn.execute("INSERT INTO mart.drop_curve VALUES (%s, %s, %s, %s)",
                             (mid, episode, drops, cumulative / 10))  # fmt: skip
            conn.execute(
                "INSERT INTO mart.critical_episode (media_id, critical_episode,"
                " critical_drop_share, point_of_no_return, nb_drops, nb_completed, drop_rate)"
                " VALUES (%s, 1, 0.5, 4, 10, 30, 0.25)",
                (mid,),
            )
        for i, kind in enumerate(("manga", "manhwa", "manhua"), start=1):
            conn.execute(
                "INSERT INTO catalog.media (kind, title, chapters, start_year, popularity,"
                " data_source) VALUES (%s, %s, 50, 2018, %s, 'anilist')",
                (kind, f"{kind.capitalize()} de test", i),
            )
        seed_embeddings(conn)


def _axis_vector(action: float, drama: float) -> str:
    v = [0.0] * EMBEDDING_DIM
    v[0], v[1] = action, drama
    norm = (action**2 + drama**2) ** 0.5
    return "[" + ",".join(str(x / norm) for x in v) + "]"


def seed_embeddings(conn: psycopg.Connection) -> None:
    """Embeddings FICTIFS (phase 10) : axe « action » pour les animes 1-8 et le manhwa, axe
    « drame » pour les animes 9-16 et le manhua, entre les deux pour le manga. Aucun modèle."""
    conn.execute(
        "INSERT INTO catalog.media_embedding (media_id, model, text_hash, embedding)"
        " SELECT id, 'e2e', 'e2e', CAST(CASE"
        "  WHEN kind = 'manhwa' OR (kind = 'anime' AND mal_id <= %(half)s) THEN %(action)s"
        "  WHEN kind = 'manga' THEN %(mixed)s ELSE %(drama)s END AS vector)"
        " FROM catalog.media",
        {"half": N_ANIME // 2, "action": _axis_vector(1, 0.05), "drama": _axis_vector(0.05, 1),
         "mixed": _axis_vector(0.6, 0.4)},
    )  # fmt: skip


def write_models(models: Path) -> None:
    half = N_ANIME // 2
    factors = np.array([[1.0, 0.05 * i] for i in range(half)]
                       + [[0.05 * i, 1.0] for i in range(half)])  # fmt: skip
    model = FoldInModel(item_ids=np.arange(1, N_ANIME + 1), factors=factors, reg_param=0.1,
                        implicit=True, alpha=1.0, rating_offset=5.0)  # fmt: skip
    models.mkdir(parents=True, exist_ok=True)
    write_reco(models, model=model, n_items=N_ANIME,
               popularity_fallback=list(range(1, N_ANIME + 1)))  # fmt: skip
    write_drop(models)


def write_settings(path: Path) -> Path:
    doc = yaml.safe_load((REPO_ROOT / "config" / "settings.yaml").read_text(encoding="utf-8"))
    for limit in ("login_limit", "register_limit"):
        doc["api"]["auth"][limit]["max_attempts"] = 10_000
    path.write_text(yaml.safe_dump(doc, allow_unicode=True), encoding="utf-8")
    return path


def main() -> None:
    url = create_database()
    seed_catalog(url)
    write_models(OUT / "models")
    settings = Settings(
        database_url=url,
        models_dir=OUT / "models",
        settings_file=write_settings(OUT / "settings.yaml"),
        jwt_secret=secrets.token_urlsafe(48),  # éphémère : propre à ce lancement
        cookie_secure=True,  # Chromium accepte un cookie Secure sur http://localhost
    )
    # Jikan simulé en panne (503 immédiat) : un test ne dépend jamais d'un service externe, et le
    # repli de /trending (« Jikan ne répond pas ») est exercé à chaque lancement.
    jikan_down = httpx.MockTransport(lambda request: httpx.Response(503))
    app = create_app(settings, load_rules(settings.settings_file), jikan_transport=jikan_down)
    print(f"API e2e prête sur http://127.0.0.1:{PORT} (base {DB_NAME})", flush=True)
    # Comme make api et l'image Docker : X-Forwarded-For ignoré (ADR 009).
    uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="warning", proxy_headers=False)


if __name__ == "__main__":
    main()
