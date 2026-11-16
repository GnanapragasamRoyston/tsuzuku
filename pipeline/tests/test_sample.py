"""Échantillon de développement par utilisateurs."""

import pytest

from tsuzuku_pipeline.spark.sample import sample_users


def _interactions(spark, n_users=5000, per_user=3):
    return spark.range(n_users * per_user).selectExpr(
        f"CAST(id DIV {per_user} AS INT) AS user_id", f"CAST(id % {per_user} AS INT) AS anime_id"
    )


def test_fraction_is_approximately_respected(spark):
    users = sample_users(_interactions(spark), 0.1, seed=42).select("user_id").distinct().count()
    assert users == pytest.approx(500, rel=0.15)


def test_keeps_all_rows_of_selected_users(spark):
    sample = sample_users(_interactions(spark), 0.1, seed=42)
    per_user = {r["count"] for r in sample.groupBy("user_id").count().collect()}
    assert per_user == {3}


def test_deterministic_and_independent_of_partitioning(spark):
    df = _interactions(spark)
    a = {r[0] for r in sample_users(df, 0.1, seed=42).select("user_id").distinct().collect()}
    b = {
        r[0]
        for r in sample_users(df.repartition(7), 0.1, seed=42)
        .select("user_id")
        .distinct()
        .collect()
    }
    assert a == b


def test_seed_changes_sample(spark):
    df = _interactions(spark)
    a = {r[0] for r in sample_users(df, 0.1, seed=1).select("user_id").distinct().collect()}
    b = {r[0] for r in sample_users(df, 0.1, seed=2).select("user_id").distinct().collect()}
    assert a != b


def test_same_users_across_tables(spark):
    # animelist et rating_complete échantillonnés séparément doivent garder les mêmes utilisateurs.
    a = sample_users(_interactions(spark, per_user=3), 0.1, seed=42)
    b = sample_users(_interactions(spark, per_user=1), 0.1, seed=42)
    users_a = {r[0] for r in a.select("user_id").distinct().collect()}
    users_b = {r[0] for r in b.select("user_id").distinct().collect()}
    assert users_a == users_b


@pytest.mark.parametrize("fraction", [0, 1.5, -0.1])
def test_invalid_fraction(spark, fraction):
    with pytest.raises(ValueError, match="fraction"):
        sample_users(_interactions(spark), fraction, seed=42)
