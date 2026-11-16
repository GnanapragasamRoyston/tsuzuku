"""Rétention par genre et par studio.

Anime 1 : Action, studio A, 10 épisodes
  2 Completed, 2 Dropped (watched 2 et 8 → progression 0.2 et 0.8), 1 Watching, 1 Plan to Watch
Anime 2 : Action + Drama, studio B, 4 épisodes
  1 Completed, 1 Dropped (watched 1 → 0.25)
Action : 3 completed, 3 dropped → drop_rate 0.5 ; commencés = 3 + 3 + 1 (watching) = 7
         completion_rate = 3/7 ; médiane des progressions (0.2, 0.8, 0.25) = 0.25
Drama  : 1 completed, 1 dropped, 1 anime.
"""

import pytest

from tsuzuku_pipeline.spark.retention_stats import StatusCodes, retention_by

CODES = StatusCodes(watching=1, completed=2, on_hold=3, dropped=4)
LIST_SCHEMA = "user_id int, anime_id int, score int, watching_status int, watched_episodes int"


def _inputs(spark):
    animelist = spark.createDataFrame(
        [
            (1, 1, 8, 2, 10),
            (2, 1, 8, 2, 10),
            (3, 1, 0, 4, 2),
            (4, 1, 0, 4, 8),
            (5, 1, 0, 1, 3),
            (6, 1, 0, 6, 0),  # Plan to Watch : pas commencé, hors dénominateur
            (7, 2, 8, 2, 4),
            (8, 2, 0, 4, 1),
        ],
        LIST_SCHEMA,
    )
    anime = spark.createDataFrame(
        [(1, 10, ["Action"], ["A"]), (2, 4, ["Action", "Drama"], ["B"])],
        "anime_id int, episodes int, genres array<string>, studios array<string>",
    )
    return animelist, anime


def _by(df, key):
    return {r[key]: r for r in df.collect()}


def test_retention_by_genre(spark):
    animelist, anime = _inputs(spark)
    rows = _by(
        retention_by(animelist, anime, "genres", "genre", CODES, min_interactions=1, min_anime=1),
        "genre",
    )
    action = rows["Action"]
    assert action["nb_anime"] == 2
    assert action["nb_completed"] == 3
    assert action["nb_dropped"] == 3
    assert action["drop_rate"] == pytest.approx(0.5)
    assert action["completion_rate"] == pytest.approx(3 / 7)
    assert action["median_drop_progress"] == pytest.approx(0.25)
    assert rows["Drama"]["nb_anime"] == 1


def test_retention_by_studio(spark):
    animelist, anime = _inputs(spark)
    rows = _by(
        retention_by(animelist, anime, "studios", "studio", CODES, min_interactions=1, min_anime=1),
        "studio",
    )
    assert set(rows) == {"A", "B"}
    assert rows["A"]["drop_rate"] == pytest.approx(0.5)


def test_volume_thresholds(spark):
    animelist, anime = _inputs(spark)
    genres = {
        r["genre"]
        for r in retention_by(
            animelist, anime, "genres", "genre", CODES, min_interactions=3, min_anime=1
        ).collect()
    }
    assert genres == {"Action"}  # Drama : 2 interactions < 3
    genres = {
        r["genre"]
        for r in retention_by(
            animelist, anime, "genres", "genre", CODES, min_interactions=1, min_anime=2
        ).collect()
    }
    assert genres == {"Action"}  # Drama : 1 anime < 2
