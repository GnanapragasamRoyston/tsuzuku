"""Filtre des contenus adultes (SPEC § 2.1) et des animes orphelins."""

from tsuzuku_pipeline.spark.adult_filter import filter_by_catalog, flag_adult

RULES = {"rating_prefixes": ["Rx"], "genres": ["Hentai"]}


def _catalog(spark):
    rows = [
        (1, "R - 17+ (violence & profanity)", ["Action"]),
        (2, "Rx - Hentai", ["Hentai"]),
        (3, "R+ - Mild Nudity", ["Hentai", "Comedy"]),  # genre Hentai sans rating Rx
        (4, "R+ - Mild Nudity", ["Ecchi"]),
        (5, None, []),  # rating inconnu : pas de preuve d'adulte, conservé
    ]
    return spark.createDataFrame(rows, "anime_id int, rating string, genres array<string>")


def test_flag_adult_rating_or_genre(spark):
    flags = {r["anime_id"]: r["is_adult"] for r in flag_adult(_catalog(spark), RULES).collect()}
    assert flags == {1: False, 2: True, 3: True, 4: False, 5: False}


def test_flag_adult_rating_prefix_is_case_sensitive_prefix_only(spark):
    df = spark.createDataFrame(
        [(1, "PG - Rx free", []), (2, "Rx", [])],
        "anime_id int, rating string, genres array<string>",
    )
    flags = {r["anime_id"]: r["is_adult"] for r in flag_adult(df, RULES).collect()}
    assert flags == {1: False, 2: True}


def test_filter_by_catalog_drops_adult_and_orphans(spark):
    allowed = flag_adult(_catalog(spark), RULES).where("NOT is_adult").select("anime_id")
    interactions = spark.createDataFrame(
        [(10, 1), (10, 2), (11, 3), (11, 4), (12, 5), (12, 999), (13, None)],
        "user_id int, anime_id int",
    )
    kept = filter_by_catalog(interactions, allowed)
    assert sorted(tuple(r) for r in kept.collect()) == [(10, 1), (11, 4), (12, 5)]
    # Le filtre ne doit pas ajouter de colonnes venant du catalogue.
    assert kept.columns == ["user_id", "anime_id"]
