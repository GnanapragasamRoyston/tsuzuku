"""Features du modèle de drop : valeurs calculées à la main, anti-fuite, parité Spark / Python.

Catalogue :
  1 : Action + Comedy, TV, 12 ép., studios [S1, S2]
  2 : Drama, Movie, 1 ép., studio S3
  3 : Action, TV, 24 ép., aucun studio
  4 : aucun genre, OVA
Utilisateur 10 : 1 Completed (note 8), 2 Dropped (non noté), 3 Dropped (note 6), 4 Plan to Watch
  ligne (10, 1) → autres = {2, 3, 4} : liste 3, C/D 2, drop 2/2 = 1.0, note moyenne 6.0,
                  parts : Action 1/3, Drama 1/3, Comedy 0 ; affinité (Action, Comedy) = (1/3 + 0)/2
  ligne (10, 2) → autres = {1, 3, 4} : drop 1/2, note (8+6)/2 = 7.0, Action 2/3, Comedy 1/3 ;
                  affinité (Drama) = 0
  ligne (10, 3) → autres = {1, 2, 4} : drop 1/2, note 8.0, Action/Comedy/Drama 1/3 ; affinité 1/3
Utilisateur 20 : une seule ligne → aucun historique : taux, note, parts et affinité à null.
"""

import math

import pytest

from tsuzuku_pipeline.ml.drop.features import (
    FORBIDDEN_COLUMNS,
    AnimeInfo,
    Entry,
    feature_columns,
    feature_row,
    genre_slug,
    spark_drop_features,
)
from tsuzuku_pipeline.spark.retention_stats import StatusCodes

CODES = StatusCodes(watching=1, completed=2, on_hold=3, dropped=4)
GENRES = ["Action", "Comedy", "Drama"]
LIST_SCHEMA = "user_id int, anime_id int, score int, watching_status int, watched_episodes int"
ANIME_SCHEMA = (
    "anime_id int, genres array<string>, type string, episodes int, duration_min double,"
    " source string, start_year int, rating string, popularity int, studios array<string>,"
    " dropped int, mal_score double"
)
CATALOG_ROWS = [
    (1, ["Action", "Comedy"], "TV", 12, 24.0, "Manga", 2010, "PG-13", 100, ["S1", "S2"], 9, 8.1),
    (2, ["Drama"], "Movie", 1, 100.0, "Original", 2015, "G", 50, ["S3"], 9, 7.0),
    (3, ["Action"], "TV", 24, 24.0, None, 2005, "R", 300, [], 9, None),
    (4, [], "OVA", None, None, None, None, None, 900, ["S1"], 9, None),
]
LIST_ROWS = [
    (10, 1, 8, 2, 12),
    (10, 2, 0, 4, 0),
    (10, 3, 6, 4, 5),
    (10, 4, 0, 6, 0),
    (10, 99, 9, 4, 3),  # anime absent du catalogue : ignoré des deux côtés (parité)
    (20, 2, 0, 2, 1),
]


@pytest.fixture
def spark_rows(spark):
    animelist = spark.createDataFrame(LIST_ROWS, LIST_SCHEMA)
    anime = spark.createDataFrame(CATALOG_ROWS, ANIME_SCHEMA)
    df = spark_drop_features(animelist, anime, CODES, GENRES)
    return {(r["user_id"], r["anime_id"]): r.asDict() for r in df.collect()}


def test_only_completed_and_dropped_rows_are_examples(spark_rows):
    assert set(spark_rows) == {(10, 1), (10, 2), (10, 3), (20, 2)}
    assert spark_rows[(10, 2)]["is_dropped"] == 1
    assert spark_rows[(10, 1)]["is_dropped"] == 0


def test_user_features_leave_one_out(spark_rows):
    r = spark_rows[(10, 1)]
    assert r["user_list_size"] == 3
    assert r["user_cd_count"] == 2
    assert r["user_drop_rate"] == pytest.approx(1.0)
    assert r["user_mean_score"] == pytest.approx(6.0)
    assert r["user_share_action"] == pytest.approx(1 / 3)
    assert r["user_share_comedy"] == pytest.approx(0.0)
    assert r["user_share_drama"] == pytest.approx(1 / 3)
    assert r["genre_affinity"] == pytest.approx(1 / 6)

    r2 = spark_rows[(10, 2)]
    assert r2["user_drop_rate"] == pytest.approx(0.5)
    assert r2["user_mean_score"] == pytest.approx(7.0)
    assert r2["genre_affinity"] == pytest.approx(0.0)

    r3 = spark_rows[(10, 3)]
    assert r3["user_mean_score"] == pytest.approx(8.0)  # la note 6 de la ligne courante est exclue
    assert r3["genre_affinity"] == pytest.approx(1 / 3)


def test_user_without_history_gets_nulls(spark_rows):
    r = spark_rows[(20, 2)]
    assert r["user_list_size"] == 0
    assert r["user_cd_count"] == 0
    for col in ["user_drop_rate", "user_mean_score", "user_share_action", "genre_affinity"]:
        assert r[col] is None


def test_anime_features(spark_rows):
    r = spark_rows[(10, 1)]
    assert (r["format"], r["episodes"], r["main_studio"]) == ("TV", 12, "S1")
    assert (r["genre_action"], r["genre_comedy"], r["genre_drama"]) == (1, 1, 0)
    assert spark_rows[(10, 3)]["main_studio"] is None  # aucun studio


def test_columns_match_contract(spark_rows):
    expected = {"user_id", "anime_id", "is_dropped", *feature_columns(GENRES)}
    assert set(next(iter(spark_rows.values()))) == expected


def test_no_forbidden_column_in_features():
    # Fuite de la cible : ces colonnes résument l'issue (ADR 004). Test bloquant.
    assert not set(feature_columns(GENRES)) & FORBIDDEN_COLUMNS
    for col in ["watched_episodes", "score", "dropped", "completed", "mal_score", "score_10"]:
        assert col in FORBIDDEN_COLUMNS


def test_genre_slug():
    assert genre_slug("Sci-Fi") == "sci_fi"
    assert genre_slug("Slice of Life") == "slice_of_life"


def _python_rows():
    catalog = {
        r[0]: AnimeInfo(
            genres=r[1], format=r[2], episodes=r[3], duration_min=r[4], source=r[5],
            start_year=r[6], age_rating=r[7], popularity=r[8], studios=r[9],
        )
        for r in CATALOG_ROWS
    }  # fmt: skip
    status = {2: "completed", 4: "dropped"}
    by_user: dict[int, list[Entry]] = {}
    for user, anime, score, code, _ in LIST_ROWS:
        by_user.setdefault(user, []).append(Entry(anime, status.get(code, "other"), score))
    return {
        (user, e.anime_id): feature_row(entries, e.anime_id, catalog, GENRES)
        for user, entries in by_user.items()
        for e in entries
        if e.status in ("completed", "dropped") and e.anime_id in catalog
    }


def _same(a, b):
    if a is None or b is None:
        return a is None and b is None
    if isinstance(a, float) or isinstance(b, float):
        return math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-12)
    return a == b


def test_spark_and_python_features_are_identical(spark_rows):
    # Parité entraînement (Spark) / production (Python pur, API phase 5) : même définition,
    # mêmes valeurs. Sans ce test, le modèle serait servi avec des features différentes.
    python_rows = _python_rows()
    assert set(python_rows) == set(spark_rows)
    for key, py in python_rows.items():
        for col in feature_columns(GENRES):
            assert _same(py[col], spark_rows[key][col]), (key, col, py[col], spark_rows[key][col])


def test_python_features_ignore_list_entries_outside_catalog():
    catalog = {1: AnimeInfo(genres=["Action"]), 2: AnimeInfo(genres=["Action"])}
    entries = [Entry(2, "completed", 9), Entry(500, "dropped", 0)]  # 500 : hors catalogue
    row = feature_row(entries, 1, catalog, ["Action"])
    assert row["user_list_size"] == 1
    assert row["user_drop_rate"] == pytest.approx(0.0)


def test_python_features_ignore_target_already_in_list():
    # En production, l'œuvre visée peut déjà être dans la liste (ex. en cours) : on l'exclut.
    catalog = {1: AnimeInfo(genres=["Action"]), 2: AnimeInfo(genres=["Action"])}
    entries = [Entry(1, "dropped", 0), Entry(2, "completed", 9)]
    row = feature_row(entries, 1, catalog, ["Action"])
    assert row["user_list_size"] == 1
    assert row["user_drop_rate"] == pytest.approx(0.0)
