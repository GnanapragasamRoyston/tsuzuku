"""Fixtures partagées : une seule SparkSession pour toute la suite (démarrer une JVM coûte ~5 s),
et une base Postgres de test dédiée pour les tests marqués `db`."""

import os

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import make_conninfo

from tsuzuku_pipeline.db import loader
from tsuzuku_pipeline.spark.session import build_spark

TEST_DB = "tsuzuku_test"

TEST_SETTINGS = {
    "project": {"seed": 42},
    "paths": {},
    # 1 cœur, peu de partitions : les jeux de test font quelques lignes.
    "spark": {"master": "local[1]", "driver_memory": "1g", "shuffle_partitions": 2},
    "data": {
        "sample_user_fraction": 0.5,
        "adult_filter": {"rating_prefixes": ["Rx"], "genres": ["Hentai"]},
    },
}


@pytest.fixture(scope="session")
def spark():
    session = build_spark(TEST_SETTINGS, app_name="tsuzuku-tests")
    session.sparkContext.setLogLevel("ERROR")
    yield session
    session.stop()


@pytest.fixture(scope="session")
def pg_url():
    """URL de la base de test, créée au besoin à côté de la base de dev (même serveur).

    Sans Postgres joignable, les tests `db` sont sautés en local, mais ÉCHOUENT si REQUIRE_DB=1
    (posé en CI) : un test sauté en silence en CI, c'est un test qui n'existe pas.
    """
    try:
        base = loader.database_url()
        with psycopg.connect(base, autocommit=True, connect_timeout=3) as admin:
            exists = admin.execute(
                "SELECT 1 FROM pg_database WHERE datname = %s", (TEST_DB,)
            ).fetchone()
            if not exists:
                admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(TEST_DB)))
    except (psycopg.OperationalError, loader.LoaderError) as exc:
        if os.environ.get("REQUIRE_DB") == "1":
            raise
        pytest.skip(f"Postgres indisponible ({type(exc).__name__}) : lance `make up`")
    return make_conninfo(base, dbname=TEST_DB)


@pytest.fixture
def pg(pg_url):
    """Connexion à une base de test remise à zéro pour chaque test.

    autocommit : sinon chaque SELECT du test ouvre une transaction qui garde un verrou sur la
    table, et le TRUNCATE du loader (autre connexion) attend ce verrou indéfiniment.
    """
    with psycopg.connect(pg_url, autocommit=True) as conn:
        conn.execute("DROP SCHEMA IF EXISTS mart CASCADE")
        conn.execute("DROP SCHEMA IF EXISTS catalog CASCADE")
        loader.apply_schemas(conn)
        yield conn


@pytest.fixture
def settings():
    return {k: (dict(v) if isinstance(v, dict) else v) for k, v in TEST_SETTINGS.items()}
