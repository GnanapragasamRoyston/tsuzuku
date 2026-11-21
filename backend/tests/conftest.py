"""Fixtures de l'API : base Postgres de test (une par exécution), petit catalogue, mini-modèles.

Les tables catalog et mart sont créées avec les MÊMES fichiers SQL que le pipeline (leur
propriétaire) : l'API est testée contre le vrai schéma, pas contre une copie.
"""

import json
import os

import httpx
import joblib
import numpy as np
import pandas as pd
import psycopg
import pytest
import sklearn
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from psycopg import sql
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline, make_pipeline
from sklearn.preprocessing import OneHotEncoder
from sqlalchemy.engine import make_url
from tsuzuku_ml.artifacts import (
    RECO_SCHEMA_VERSION,
    drop_paths,
    reco_paths,
    sha256_file,
)
from tsuzuku_ml.drop_features import CATEGORICAL_COLUMNS, feature_columns, prepare_x
from tsuzuku_ml.fold_in import FoldInModel, fold_in, recommend

from app.core.config import REPO_ROOT, Settings, load_rules
from app.main import create_app

TEST_DB = f"tsuzuku_api_test_{os.getpid()}"
BACKEND_DIR = REPO_ROOT / "backend"
# Secret propre aux tests (jamais utilisé ailleurs) ; 64 caractères comme celui de make api-keys.
TEST_JWT_SECRET = "test-only-" + "x" * 54
SCHEMA_DIR = REPO_ROOT / "pipeline" / "src" / "tsuzuku_pipeline" / "db"
GENRES = ["Action", "Drama"]


def alembic_config(url: str) -> Config:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.attributes["database_url"] = url
    # Sans ça, fileConfig reconfigurerait les loggers et casserait caplog dans les tests suivants.
    cfg.attributes["configure_logger"] = False
    return cfg


def _base_url() -> str:
    from dotenv import dotenv_values

    url = os.environ.get("DATABASE_URL") or dotenv_values(REPO_ROOT / ".env").get("DATABASE_URL")
    if not url:
        raise KeyError("DATABASE_URL")
    # Les tests (et l'API e2e) CRÉENT et SUPPRIMENT des bases sur ce serveur : jamais ailleurs
    # qu'en local, sauf en CI (Postgres jetable du runner). Garde-fou si .env pointe un jour
    # vers une base hébergée (Neon, phase 11).
    host = make_url(url).host
    if host not in ("localhost", "127.0.0.1", "::1") and os.environ.get("CI") != "1":
        raise RuntimeError(f"tests refusés sur un serveur Postgres distant ({host})")
    return url


@pytest.fixture(scope="session")
def pg_url():
    name = sql.Identifier(TEST_DB)
    try:
        base = _base_url()
        with psycopg.connect(base, autocommit=True, connect_timeout=3) as admin:
            admin.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(name))
            admin.execute(sql.SQL("CREATE DATABASE {}").format(name))
    except (psycopg.OperationalError, KeyError) as exc:
        if os.environ.get("REQUIRE_DB") == "1":
            raise
        pytest.skip(f"Postgres indisponible ({type(exc).__name__}) : lance `make up`")
    # Format URL (et non « clé=valeur ») : lisible à la fois par psycopg et par SQLAlchemy.
    url = make_url(base).set(database=TEST_DB).render_as_string(hide_password=False)
    with psycopg.connect(url, autocommit=True) as conn:
        for f in ("schema_catalog.sql", "schema_mart.sql"):
            conn.execute((SCHEMA_DIR / f).read_text(encoding="utf-8"))
    # Schéma app : créé par les VRAIES migrations, comme en dev et en production.
    command.upgrade(alembic_config(url), "head")
    yield url
    with psycopg.connect(base, autocommit=True, connect_timeout=3) as admin:
        admin.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(name))


# Catalogue de test : 8 animes (mal_id 1-8), deux groupes de goûts (1-4 / 5-8), plus un manga.
ANIME = [
    (mal, f"Anime {mal}", "TV" if mal % 2 else "Movie", 12 * mal, 2000 + mal, 100 - mal,
     ["Action"] if mal <= 4 else ["Drama"], [f"Studio {mal % 2}"])
    for mal in range(1, 9)
]  # fmt: skip


@pytest.fixture(scope="session")
def catalog(pg_url):
    """{mal_id: media_id} des animes, et l'id du manga."""
    with psycopg.connect(pg_url, autocommit=True) as conn:
        conn.execute("TRUNCATE catalog.media, catalog.genre RESTART IDENTITY CASCADE")
        genre_ids = {
            g: conn.execute(
                "INSERT INTO catalog.genre (name) VALUES (%s) RETURNING id", (g,)
            ).fetchone()[0]  # fmt: skip
            for g in GENRES
        }
        ids = {}
        for mal, title, fmt, eps, year, pop, genres, studios in ANIME:
            mid = conn.execute(
                "INSERT INTO catalog.media (kind, mal_id, title, title_alt, format, episodes,"
                " start_year, popularity, creators, source, age_rating, duration_min, data_source)"
                " VALUES ('anime', %s, %s, %s, %s, %s, %s, %s, %s, 'Manga', 'PG-13', 24,"
                " 'mal_kaggle_2020') RETURNING id",
                (mal, title, f"Alt {mal}", fmt, eps, year, pop, studios),
            ).fetchone()[0]
            ids[mal] = mid
            for g in genres:
                conn.execute("INSERT INTO catalog.media_genre VALUES (%s, %s)", (mid, genre_ids[g]))
        manga = conn.execute(
            "INSERT INTO catalog.media (kind, mal_id, title, data_source)"
            " VALUES ('manga', 1, 'Manga 1', 'anilist') RETURNING id"
        ).fetchone()[0]
        # Anime récent ajouté par Jikan : hors données d'entraînement des deux modèles.
        recent = conn.execute(
            "INSERT INTO catalog.media (kind, mal_id, title, format, episodes, data_source)"
            " VALUES ('anime', 50000, 'Saison 2026', 'TV', 12, 'jikan') RETURNING id"
        ).fetchone()[0]
        conn.execute(
            "INSERT INTO mart.critical_episode VALUES (%s, 3, 0.2, 0.1, 5, 120, 900, 0.12)",
            (ids[1],),
        )
        for ep, n, share in ((1, 30, 0.25), (3, 50, 0.67), (5, 40, 1.0)):
            conn.execute("INSERT INTO mart.drop_curve VALUES (%s, %s, %s, %s)",
                         (ids[1], ep, n, share))  # fmt: skip
    return {"anime": ids, "manga": manga, "recent": recent}


def _reco_model() -> FoldInModel:
    # Groupe 1-4 sur l'axe x, groupe 5-8 sur l'axe y : des goûts bien séparés.
    factors = np.array([[1.0, 0.05 * i] for i in range(4)] + [[0.05 * i, 1.0] for i in range(4)])
    return FoldInModel(item_ids=np.arange(1, 9), factors=factors, reg_param=0.1, implicit=True,
                       alpha=1.0, rating_offset=5.0)  # fmt: skip


def write_reco(models, model=None, **changes):
    model = model or _reco_model()
    factors_path, card_path = reco_paths(models)
    pd.DataFrame({"anime_id": model.item_ids, "factors": list(model.factors)}).to_parquet(
        factors_path, index=False
    )
    liked = [1, 2]
    vec = fold_in(model, np.array(liked), np.array([8.0, 8.0]))
    card = {
        "run_id": "reco-test",
        "schema_version": RECO_SCHEMA_VERSION,
        "n_items": len(model.item_ids),
        "fold_in": {"rank": model.rank, "reg_param": 0.1, "implicit": True, "alpha": 1.0,
                    "rating_offset": 5.0},
        "onboarding_default_score": 8,
        "relevant_min_score": 8,
        "popularity_fallback": [8, 7, 6, 5, 4, 3, 2, 1],
        "parity_check": {"anime_ids": liked, "scores": [8.0, 8.0],
                         "expected_top10": recommend(model, vec, exclude=liked, k=6).tolist()},
        "artifact_sha256": sha256_file(factors_path),
        **changes,
    }  # fmt: skip
    card_path.write_text(json.dumps(card))


def write_drop(models, genres=GENRES, without=()):
    """Mini modèle de drop. `genres` ≠ GENRES → pickle et fiche incohérents ; `without` : clés
    retirées de la fiche."""
    cols = feature_columns(GENRES)
    numeric = [c for c in cols if c not in CATEGORICAL_COLUMNS]
    pipe = Pipeline([
        ("prep", ColumnTransformer([
            ("cat", make_pipeline(SimpleImputer(strategy="constant", fill_value="__missing__"),
                                  OneHotEncoder(handle_unknown="ignore")),
             list(CATEGORICAL_COLUMNS)),
            ("num", SimpleImputer(strategy="constant", fill_value=0.0), numeric),
        ])),
        ("model", LogisticRegression(max_iter=200)),
    ])  # fmt: skip
    rng = np.random.default_rng(0)
    rows = pd.DataFrame([{c: (None if c in CATEGORICAL_COLUMNS else rng.random()) for c in cols}
                         for _ in range(40)])  # fmt: skip
    rows["format"] = rng.choice(["TV", "Movie"], size=40)
    y = (rows["user_drop_rate"] > 0.5).astype(int)
    pipe.fit(prepare_x(rows, GENRES), y)
    model_path, card_path = drop_paths(models)
    joblib.dump(pipe, model_path)
    card = {
        "run_id": "drop-test", "genres": list(genres), "threshold": 0.5,
        "versions": {"scikit-learn": sklearn.__version__},
        "artifact_sha256": sha256_file(model_path),
    }  # fmt: skip
    card_path.write_text(json.dumps({k: v for k, v in card.items() if k not in without}))


@pytest.fixture
def models_dir(tmp_path):
    models = tmp_path / "models"
    models.mkdir()
    write_reco(models)
    write_drop(models)
    return models


class FakeJikan:
    """Transport httpx simulé : compte les appels, renvoie une saison ou des erreurs."""

    def __init__(self, statuses=None):
        self.calls = 0
        self.statuses = list(statuses or [])

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.calls += 1
        if self.statuses:
            return httpx.Response(self.statuses.pop(0))
        data = [
            {"mal_id": 1, "title": "Anime 1", "members": 10, "score": 8.1, "rating": "PG-13",
             "genres": [{"name": "Action"}], "images": {"jpg": {"image_url": "http://img/1"}}},
            {"mal_id": 999, "title": "Nouveauté", "members": 50, "rating": "PG-13", "genres": []},
            {"mal_id": 666, "title": "Adulte", "members": 99, "rating": "Rx - Hentai",
             "genres": [{"name": "Hentai"}]},
        ]  # fmt: skip
        return httpx.Response(200, json={"data": data, "pagination": {"has_next_page": False}})


@pytest.fixture
def jikan():
    return FakeJikan()


@pytest.fixture
def make_client(pg_url, catalog, models_dir, jikan):
    """Fabrique de client : chaque test peut changer les modèles, Jikan ou la base."""
    clients = []

    def factory(models=None, transport=None, database_url=None, jwt_secret=TEST_JWT_SECRET,
                rules=None, **rule_changes):  # fmt: skip
        settings = Settings(database_url=database_url or pg_url, models_dir=models or models_dir,
                            settings_file=REPO_ROOT / "config" / "settings.yaml",
                            jwt_secret=jwt_secret, cookie_secure=True)  # fmt: skip
        rules = rules or load_rules(settings.settings_file)
        if rule_changes:
            rules = rules.model_copy(update=rule_changes)
        app = create_app(settings, rules, jikan_transport=httpx.MockTransport(transport or jikan))
        # HTTPS : le cookie de session est `Secure`, le client ne le renverrait pas en http.
        client = TestClient(app, base_url="https://testserver")
        client.__enter__()  # déclenche le lifespan (chargement des modèles)
        clients.append(client)
        return client

    yield factory
    for c in clients:
        c.__exit__(None, None, None)


@pytest.fixture
def client(make_client):
    return make_client()


# --- Comptes (phase 7) -----------------------------------------------------------------------
PASSWORD = "un-mot-de-passe-solide"  # noqa: S105  (compte de test)


@pytest.fixture
def clean_users(pg_url):
    """Chaque test de compte part de zéro (les listes et choix suivent par cascade)."""
    with psycopg.connect(pg_url, autocommit=True) as conn:
        conn.execute("TRUNCATE app.users RESTART IDENTITY CASCADE")


def register(client, pseudo="royston", email=None, password=PASSWORD):
    """Inscrit un compte : le client garde le cookie de session (connecté)."""
    email = email or f"{pseudo}@example.com"
    return client.post("/auth/register",
                       json={"email": email, "pseudo": pseudo, "password": password})  # fmt: skip


@pytest.fixture
def user_client(make_client, clean_users):
    """Client connecté avec un compte tout neuf."""
    client = make_client()
    assert register(client).status_code == 201
    return client
