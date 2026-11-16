"""Fixtures partagées : une seule SparkSession pour toute la suite (démarrer une JVM coûte ~5 s)."""

import pytest

from tsuzuku_pipeline.spark.session import build_spark

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


@pytest.fixture
def settings():
    return {k: (dict(v) if isinstance(v, dict) else v) for k, v in TEST_SETTINGS.items()}
