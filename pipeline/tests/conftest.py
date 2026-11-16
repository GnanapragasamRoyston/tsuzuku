"""Fixtures partagées : une seule SparkSession pour toute la suite (démarrer une JVM coûte ~5 s),
et une base Postgres de test dédiée pour les tests marqués `db`."""

import os

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import make_conninfo

from tsuzuku_pipeline.db import loader
from tsuzuku_pipeline.spark.session import build_spark

# Une base PAR exécution de pytest (suffixe = pid) : deux suites lancées en même temps (ex. un
# relecteur qui lance les tests pendant les miens) partageaient « tsuzuku_test » ; leurs DROP
# SCHEMA s'attendaient mutuellement et la suite se bloquait sans fin (vécu en phase 3).
TEST_DB = f"tsuzuku_test_{os.getpid()}"

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
    name = sql.Identifier(TEST_DB)
    try:
        base = loader.database_url()
        with psycopg.connect(base, autocommit=True, connect_timeout=3) as admin:
            admin.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(name))
            admin.execute(sql.SQL("CREATE DATABASE {}").format(name))
    except (psycopg.OperationalError, loader.LoaderError) as exc:
        if os.environ.get("REQUIRE_DB") == "1":
            raise
        pytest.skip(f"Postgres indisponible ({type(exc).__name__}) : lance `make up`")
    yield make_conninfo(base, dbname=TEST_DB)
    # Nettoyage : la base de cette exécution disparaît avec elle. WITH (FORCE) ferme une
    # connexion de test restée ouverte au lieu d'attendre.
    with psycopg.connect(base, autocommit=True, connect_timeout=3) as admin:
        admin.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(name))


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
