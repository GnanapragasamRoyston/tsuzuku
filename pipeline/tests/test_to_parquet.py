"""Lecture des CSV bruts et typage (couche staging)."""

import pytest

from tsuzuku_pipeline.spark.to_parquet import (
    clean_anime,
    clean_synopsis,
    read_anime,
    read_interactions,
    read_synopsis,
    read_watching_status,
)

ANIME_HEADER = (
    "MAL_ID,Name,Score,Genres,English name,Japanese name,Type,Episodes,Aired,Premiered,Producers,"
    "Licensors,Studios,Source,Duration,Rating,Ranked,Popularity,Members,Favorites,Watching,"
    "Completed,On-Hold,Dropped,Plan to Watch,Score-10,Score-9,Score-8,Score-7,Score-6,Score-5,"
    "Score-4,Score-3,Score-2,Score-1"
)
TAIL = ",1,2,3,4,5,6.0,7.0,8.0,9.0,10.0,11.0,12.0,13.0,14.0,15.0"
ANIME_ROWS = [
    '1,Cowboy Bebop,8.78,"Action, Sci-Fi",Cowboy Bebop,x,TV,26,"Apr 3, 1998 to Apr 24, 1999",'
    'Spring 1998,Bandai Visual,"Funimation, Bandai",Sunrise,Original,24 min. per ep.,'
    "R - 17+ (violence & profanity),28.0,39,1251960" + TAIL,
    '5,"Movie, ""quoted""",Unknown,Drama,Unknown,x,Movie,Unknown,2005,Unknown,Unknown,Unknown,'
    "Unknown,Unknown,1 hr. 55 min.,Unknown,Unknown,518,273145" + TAIL,
    "9,Short,6.1,Unknown,Unknown,x,Unknown,1,Unknown,Unknown,Unknown,Unknown,Unknown,Manga,"
    "30 sec.,G - All Ages,Unknown,7,10" + TAIL,
]


@pytest.fixture
def anime_csv(tmp_path):
    path = tmp_path / "anime.csv"
    path.write_text("\n".join([ANIME_HEADER, *ANIME_ROWS]) + "\n", encoding="utf-8")
    return path


def _by_id(df):
    return {r["anime_id"]: r for r in df.collect()}


def test_clean_anime_types_and_unknowns(spark, anime_csv):
    rows = _by_id(clean_anime(read_anime(spark, anime_csv)))
    bebop, movie, short = rows[1], rows[5], rows[9]

    assert bebop["name"] == "Cowboy Bebop"
    assert bebop["mal_score"] == pytest.approx(8.78)
    assert bebop["episodes"] == 26
    assert bebop["genres"] == ["Action", "Sci-Fi"]
    assert bebop["studios"] == ["Sunrise"]
    assert bebop["licensors"] == ["Funimation", "Bandai"]
    assert bebop["type"] == "TV"
    assert bebop["rating"] == "R - 17+ (violence & profanity)"
    assert bebop["members"] == 1251960
    assert bebop["ranked"] == 28

    # "Unknown" devient null (valeurs) ou liste vide (listes), jamais la chaîne "Unknown".
    assert movie["name"] == 'Movie, "quoted"'
    assert movie["mal_score"] is None
    assert movie["episodes"] is None
    assert movie["rating"] is None
    assert movie["studios"] == []
    assert short["genres"] == []
    assert short["type"] is None


def test_clean_anime_duration_in_minutes(spark, anime_csv):
    rows = _by_id(clean_anime(read_anime(spark, anime_csv)))
    assert rows[1]["duration_min"] == pytest.approx(24.0)
    assert rows[5]["duration_min"] == pytest.approx(115.0)
    assert rows[9]["duration_min"] == pytest.approx(0.5)


def test_clean_anime_year_and_season(spark, anime_csv):
    rows = _by_id(clean_anime(read_anime(spark, anime_csv)))
    assert rows[1]["start_year"] == 1998
    assert rows[1]["premiered_season"] == "Spring"
    assert rows[5]["start_year"] == 2005  # format "2005" seul
    assert rows[5]["premiered_season"] is None
    assert rows[9]["start_year"] is None


def test_clean_anime_keeps_aggregate_columns_snake_case(spark, anime_csv):
    # Gardées en staging pour l'EDA et Power BI, mais INTERDITES comme features (fuite, ADR 002).
    cols = clean_anime(read_anime(spark, anime_csv)).columns
    for c in ["dropped", "completed", "on_hold", "plan_to_watch", "score_10", "score_1"]:
        assert c in cols


def test_read_interactions_renames_and_types(spark, tmp_path):
    path = tmp_path / "animelist.csv"
    path.write_text(
        "user_id,anime_id,rating,watching_status,watched_episodes\n0,67,9,1,1\n1,x,7,2,3\n",
        encoding="utf-8",
    )
    df = read_interactions(spark, path, with_status=True)
    assert df.columns == ["user_id", "anime_id", "score", "watching_status", "watched_episodes"]
    rows = df.orderBy("user_id").collect()
    assert tuple(rows[0]) == (0, 67, 9, 1, 1)
    # Valeur non numérique : null (comptée par le rapport qualité), pas d'exception ni de perte.
    assert rows[1]["anime_id"] is None


def test_read_rating_complete(spark, tmp_path):
    path = tmp_path / "rating_complete.csv"
    path.write_text("user_id,anime_id,rating\n0,430,9\n", encoding="utf-8")
    df = read_interactions(spark, path, with_status=False)
    assert df.columns == ["user_id", "anime_id", "score"]


def test_read_watching_status_strips_header_spaces(spark, tmp_path):
    path = tmp_path / "watching_status.csv"
    path.write_text(
        "status, description\n1,Currently Watching\n6,Plan to Watch\n", encoding="utf-8"
    )
    rows = read_watching_status(spark, path).orderBy("status").collect()
    assert [tuple(r) for r in rows] == [(1, "Currently Watching"), (6, "Plan to Watch")]


def test_synopsis_multiline_and_typo_fixed(spark, tmp_path):
    path = tmp_path / "anime_with_synopsis.csv"
    path.write_text(
        'MAL_ID,Name,Score,Genres,sypnopsis\n1,A,8.0,"Action, Drama","Line one\nline ""two"""\n'
        "2,B,Unknown,Unknown,\n",
        encoding="utf-8",
    )
    rows = {r["anime_id"]: r for r in clean_synopsis(read_synopsis(spark, path)).collect()}
    assert rows[1]["synopsis"] == 'Line one\nline "two"'
    assert rows[2]["synopsis"] is None
    assert len(rows) == 2
