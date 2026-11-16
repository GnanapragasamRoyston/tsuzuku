"""Nettoyage staging → clean des tables d'interactions."""

from tsuzuku_pipeline.spark.clean import clean_interactions

SCHEMA = "user_id int, anime_id int, score int, watching_status int, watched_episodes int"


def test_clean_interactions_applies_every_rule(spark):
    rows = [
        (1, 10, 8, 2, 12),
        (1, 10, 8, 2, 12),  # doublon exact → une seule copie gardée
        (1, 11, 0, 1, 3),  # anime 11 non autorisé (adulte)
        (2, 10, 5, 5, 1),  # statut 5 inconnu
        (2, 10, 5, None, 1),  # statut illisible
        (3, 13, 6, 2, 1),  # orphelin
        (None, 10, 5, 2, 1),  # clé nulle
        (4, 12, 7, 6, 0),
    ]
    df = spark.createDataFrame(rows, SCHEMA)
    allowed = spark.createDataFrame([(10,), (12,)], "anime_id int")

    kept = clean_interactions(df, allowed, valid_statuses=[1, 2, 3, 4, 6])
    assert kept.columns == df.columns
    assert sorted(tuple(r) for r in kept.collect()) == [(1, 10, 8, 2, 12), (4, 12, 7, 6, 0)]


def test_clean_interactions_without_status_column(spark):
    df = spark.createDataFrame(
        [(1, 10, 9), (1, 10, 9), (2, 11, 7)], "user_id int, anime_id int, score int"
    )
    allowed = spark.createDataFrame([(10,)], "anime_id int")
    assert [tuple(r) for r in clean_interactions(df, allowed).collect()] == [(1, 10, 9)]
