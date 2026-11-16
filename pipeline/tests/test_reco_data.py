import pytest
from pyspark.sql import functions as F

from tsuzuku_pipeline.ml.reco.data import assign_split, filter_active, mask_holdout, user_bucket


def _ratings(spark, rows):
    return spark.createDataFrame(rows, "user_id INT, anime_id INT, score INT")


def test_filter_active_iterates_until_stable(spark):
    # Seuils : utilisateur ≥ 2 notes, anime ≥ 2 notes.
    # L'anime 30 n'a qu'une note → retiré ; l'utilisateur 3 tombe alors à 1 note → retiré ;
    # l'anime 20 tombe alors à 1 note → retiré ; l'utilisateur 2 tombe à 1 note → retiré.
    # Une seule passe garderait des lignes sous les seuils.
    rows = [
        (1, 10, 8), (1, 40, 7),
        (2, 10, 6), (2, 20, 5),
        (3, 20, 9), (3, 30, 4),
        (4, 10, 7), (4, 40, 8),
    ]  # fmt: skip
    kept, rounds = filter_active(_ratings(spark, rows), min_user_ratings=2, min_item_ratings=2)
    got = sorted((r.user_id, r.anime_id) for r in kept.collect())
    assert got == [(1, 10), (1, 40), (4, 10), (4, 40)]
    assert rounds >= 2


def test_filter_active_rejects_bad_thresholds(spark):
    with pytest.raises(ValueError, match="seuil"):
        filter_active(_ratings(spark, [(1, 1, 5)]), min_user_ratings=0, min_item_ratings=1)


def test_filter_active_stops_after_max_rounds(spark):
    rows = [(1, 10, 8), (1, 40, 7), (2, 10, 6), (2, 20, 5), (3, 20, 9), (3, 30, 4)]
    with pytest.raises(RuntimeError, match="stable"):
        filter_active(_ratings(spark, rows), 2, 2, max_rounds=1)


def test_assign_split_is_per_user_and_reproducible(spark):
    rows = [(u, a, 7) for u in range(200) for a in (1, 2, 3)]
    df = _ratings(spark, rows)
    a = assign_split(df, val_fraction=0.1, test_fraction=0.1, seed=42)
    b = assign_split(df, val_fraction=0.1, test_fraction=0.1, seed=42)
    # Un utilisateur a une seule partie : jamais à la fois en train et en test.
    per_user = a.groupBy("user_id").agg(F.countDistinct("split").alias("n"))
    assert per_user.where("n > 1").count() == 0
    assert sorted(a.collect()) == sorted(b.collect())
    counts = {r.split: r["count"] for r in a.groupBy("split").count().collect()}
    assert set(counts) == {"train", "val", "test"}
    # Proportions approximatives sur 200 utilisateurs (600 lignes).
    assert 0.65 < counts["train"] / 600 < 0.95


def test_assign_split_rejects_bad_fractions(spark):
    df = _ratings(spark, [(1, 1, 5)])
    with pytest.raises(ValueError, match="fraction"):
        assign_split(df, val_fraction=0.6, test_fraction=0.5, seed=1)


def test_mask_holdout_masks_only_eval_rows(spark):
    rows = [(u, a, 7) for u in range(100) for a in range(20)]
    split = assign_split(_ratings(spark, rows), 0.2, 0.2, seed=42)
    masked = mask_holdout(split, mask_fraction=0.3, seed=42)
    assert masked.where("split = 'train' AND masked").count() == 0
    share = masked.where("split != 'train'").agg(F.mean(F.col("masked").cast("double"))).first()[0]
    assert 0.2 < share < 0.4
    again = mask_holdout(split, mask_fraction=0.3, seed=42)
    assert sorted(masked.collect()) == sorted(again.collect())


def test_user_bucket_salts_are_independent(spark):
    df = _ratings(spark, [(u, 1, 5) for u in range(500)])
    a = {r.user_id for r in df.where(user_bucket("a", 42) < 0.5).collect()}
    b = {r.user_id for r in df.where(user_bucket("b", 42) < 0.5).collect()}
    # Deux tirages avec des sels différents ne doivent pas sélectionner les mêmes utilisateurs.
    assert a != b
