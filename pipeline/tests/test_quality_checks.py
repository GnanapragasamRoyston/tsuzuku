"""Métriques du rapport qualité, vérifiées sur des jeux dont on connaît la réponse."""

import json

from tsuzuku_pipeline.spark.clean import clean_interactions
from tsuzuku_pipeline.spark.quality_checks import (
    catalog_metrics,
    filter_metrics,
    interaction_metrics,
    pairs_missing_from,
    render_markdown,
)

LIST_SCHEMA = "user_id int, anime_id int, score int, watching_status int, watched_episodes int"


def _animelist(spark):
    rows = [
        (1, 10, 8, 2, 12),
        (1, 10, 8, 2, 12),  # doublon exact
        (1, 11, 0, 1, 3),  # score 0 = non noté
        (2, 10, 11, 4, 2),  # score hors plage
        (2, 12, 5, 5, 1),  # statut 5 : n'existe pas dans watching_status.csv
        (3, 11, 7, 2, 30),  # 30 épisodes vus pour un anime qui en a 24
        (3, 13, 6, 2, -1),  # épisodes négatifs ; anime 13 orphelin
        (None, 10, 5, 2, 1),  # clé nulle
    ]
    return spark.createDataFrame(rows, LIST_SCHEMA)


def _episodes(spark):
    return spark.createDataFrame([(10, 12), (11, 24), (12, None)], "anime_id int, episodes int")


def test_interaction_metrics_animelist(spark):
    m = interaction_metrics(
        _animelist(spark), score_range=(0, 10), statuses={1: "W", 2: "C", 4: "D", 6: "P"},
        episodes=_episodes(spark),
    )  # fmt: skip
    assert m["rows"] == 8
    assert m["null_keys"] == 1
    assert m["distinct_users"] == 3
    assert m["distinct_anime"] == 4
    assert m["duplicate_pairs"] == 1
    assert m["score_out_of_range"] == 1
    assert m["score_zero"] == 1
    assert m["unknown_status_rows"] == 1
    assert m["status_counts"] == {"C": 4, "W": 1, "D": 1, "unknown(5)": 1}
    assert m["negative_watched_episodes"] == 1
    assert m["watched_gt_episodes"] == 1
    json.dumps(m)  # doit rester sérialisable


def test_interaction_metrics_rating_complete_has_no_status(spark):
    df = spark.createDataFrame([(1, 10, 9), (1, 11, 0)], "user_id int, anime_id int, score int")
    m = interaction_metrics(df, score_range=(1, 10))
    assert m["score_out_of_range"] == 1
    assert "status_counts" not in m


def test_catalog_metrics(spark):
    df = spark.createDataFrame(
        [
            (1, "Rx - Hentai", ["Hentai"], True, 12, 8.0),
            (2, "R+ - Mild Nudity", ["Hentai"], True, 1, None),
            (3, None, [], False, None, 7.0),
            (4, "G - All Ages", ["Kids"], False, 24, 6.5),
        ],
        "anime_id int, rating string, genres array<string>, is_adult boolean, episodes int,"
        " mal_score double",
    )
    m = catalog_metrics(df, rating_prefixes=["Rx"])
    assert m["rows"] == 4
    assert m["adult_total"] == 2
    assert m["adult_by_genre_only"] == 1
    assert m["unknown_rating"] == 1
    assert m["empty_genres"] == 1
    assert m["null_counts"]["episodes"] == 1
    assert m["null_counts"]["mal_score"] == 1


def test_unknown_status_counts_null_status(spark):
    df = spark.createDataFrame([(1, 10, 8, None, 1), (1, 11, 8, 2, 1)], LIST_SCHEMA)
    m = interaction_metrics(df, score_range=(0, 10), statuses={2: "C"})
    assert m["unknown_status_rows"] == 1


def test_catalog_metrics_counts_duplicate_ids(spark):
    df = spark.createDataFrame(
        [(1, "G", ["Kids"], False), (1, "G", ["Kids"], False), (2, "G", [], False)],
        "anime_id int, rating string, genres array<string>, is_adult boolean",
    )
    assert catalog_metrics(df, rating_prefixes=["Rx"])["duplicate_anime_ids"] == 1


def _filter_case(spark, catalog_rows):
    staging = _animelist(spark)
    catalog = spark.createDataFrame(catalog_rows, "anime_id int, is_adult boolean")
    statuses = [1, 2, 4, 6]
    allowed = catalog.where("NOT is_adult").select("anime_id")
    clean = clean_interactions(staging, allowed, valid_statuses=statuses)
    return filter_metrics(staging, clean, catalog, valid_statuses=statuses)


EXPECTED_FILTER = {
    "rows_before": 8,
    "removed_null_keys": 1,
    "removed_unknown_status": 1,
    "removed_duplicates": 1,
    "removed_adult": 2,
    "removed_orphan": 1,
    "orphan_anime_ids": 1,
    "rows_after": 2,
}


def test_filter_metrics_breakdown_adds_up(spark):
    m = _filter_case(spark, [(10, False), (11, True), (12, False)])
    assert m == EXPECTED_FILTER
    removed = sum(v for k, v in m.items() if k.startswith("removed_"))
    assert m["rows_before"] - removed == m["rows_after"]


def test_filter_metrics_robust_to_duplicate_catalog_ids(spark):
    # Un anime_id présent deux fois dans le catalogue ne doit pas doubler les comptes.
    m = _filter_case(spark, [(10, False), (10, False), (11, True), (11, True), (12, False)])
    assert m == EXPECTED_FILTER


def test_pairs_missing_from(spark):
    ratings = spark.createDataFrame(
        [(1, 10), (1, 11), (2, 12), (4, 10)], "user_id int, anime_id int"
    )
    # Seule (4, 10) n'a pas d'équivalent dans animelist.
    assert pairs_missing_from(ratings, _animelist(spark)) == 1


def test_render_markdown_contains_key_numbers():
    report = {
        "generated_at": "2026-11-16T00:00:00Z",
        "dataset": "owner/ds",
        "license": "CC0-1.0",
        "tables": {"animelist": {"rows": 1234567, "status_counts": {"Completed": 3}}},
        "filters": {"animelist": {"rows_before": 10, "rows_after": 7}},
    }
    md = render_markdown(report)
    assert "# Rapport qualité" in md
    assert "1 234 567" in md
    assert "CC0-1.0" in md
    assert "Completed" in md
