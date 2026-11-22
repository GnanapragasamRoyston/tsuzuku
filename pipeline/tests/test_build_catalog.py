"""Construction des lignes du catalogue anime (catalog.media / genre / media_genre)."""

from tsuzuku_pipeline.spark.build_catalog import MEDIA_COLUMNS, media_genres, media_rows


def _anime(spark):
    return spark.createDataFrame(
        [
            (1, "Cowboy Bebop", "Cowboy Bebop", 26, "TV", 24.0, 1998, ["Sunrise"], "Original",
             "R - 17+ (violence & profanity)", 39, ["Action", "Sci-Fi"]),
            (5, "Film", None, 1, "Movie", 115.0, 2001, [], None, None, 518, ["Drama", "Action"]),
        ],
        "anime_id int, name string, english_name string, episodes int, type string,"
        " duration_min double, start_year int, studios array<string>, source string,"
        " rating string, popularity int, genres array<string>",
    )  # fmt: skip


def _synopsis(spark):
    return spark.createDataFrame([(1, "Space cowboys.")], "anime_id int, synopsis string")


def test_media_rows_map_spec_columns(spark):
    rows = {r["mal_id"]: r for r in media_rows(_anime(spark), _synopsis(spark)).collect()}
    bebop = rows[1]
    assert bebop["kind"] == "anime"
    assert bebop["title"] == "Cowboy Bebop"
    # Titres identiques : pas de titre secondaire en double.
    assert bebop["title_alt"] is None
    assert bebop["synopsis"] == "Space cowboys."
    assert bebop["episodes"] == 26
    assert bebop["format"] == "TV"
    assert bebop["start_year"] == 1998
    assert bebop["creators"] == ["Sunrise"]
    assert bebop["age_rating"] == "R - 17+ (violence & profanity)"
    assert bebop["popularity"] == 39
    # Pas de synopsis : null, et l'anime reste dans le catalogue.
    assert rows[5]["synopsis"] is None


def test_media_rows_column_order_is_stable(spark):
    # Le loader fait un COPY par position : l'ordre des colonnes est un contrat.
    assert media_rows(_anime(spark), _synopsis(spark)).columns == list(MEDIA_COLUMNS)


def test_media_genres_one_row_per_pair(spark):
    pairs = sorted(tuple(r) for r in media_genres(_anime(spark)).collect())
    assert pairs == [(1, "Action"), (1, "Sci-Fi"), (5, "Action"), (5, "Drama")]


def test_media_rows_show_the_english_title_first(spark):
    anime = spark.createDataFrame(
        [(16498, "Shingeki no Kyojin", "Attack on Titan", 25, "TV", 24.0, 2013, ["Wit"], "Manga",
          "R", 1, ["Action"])],
        "anime_id int, name string, english_name string, episodes int, type string,"
        " duration_min double, start_year int, studios array<string>, source string,"
        " rating string, popularity int, genres array<string>",
    )  # fmt: skip
    row = media_rows(anime, _synopsis(spark)).collect()[0]
    assert (row["title"], row["title_alt"]) == ("Attack on Titan", "Shingeki no Kyojin")


def test_media_rows_ignore_an_english_title_that_only_differs_by_punctuation(spark):
    anime = spark.createDataFrame(
        [(5114, "Fullmetal Alchemist: Brotherhood", "Fullmetal Alchemist:Brotherhood", 64, "TV",
          24.0, 2009, ["Bones"], "Manga", "R", 3, ["Action"])],
        "anime_id int, name string, english_name string, episodes int, type string,"
        " duration_min double, start_year int, studios array<string>, source string,"
        " rating string, popularity int, genres array<string>",
    )  # fmt: skip
    row = media_rows(anime, _synopsis(spark)).collect()[0]
    assert (row["title"], row["title_alt"]) == ("Fullmetal Alchemist: Brotherhood", None)


def test_media_rows_keep_the_romaji_without_english_title(spark):
    rows = {r["mal_id"]: r for r in media_rows(_anime(spark), _synopsis(spark)).collect()}
    assert (rows[5]["title"], rows[5]["title_alt"]) == ("Film", None)
