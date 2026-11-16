"""Fold-in : le vecteur d'un utilisateur calculé en NumPy doit être celui que Spark aurait calculé.

Test de parité : Spark ALS met à jour les utilisateurs EN DERNIER à chaque itération, donc ses
facteurs utilisateur sont exactement la solution des moindres carrés régularisés étant donnés les
facteurs des animes finaux. Notre fold-in, appliqué aux mêmes notes, doit retrouver ces vecteurs.
"""

import numpy as np
import pandas as pd
import pytest
from pyspark.ml.recommendation import ALS

from tsuzuku_pipeline.ml.reco.fold_in import (
    FoldInModel,
    fold_in,
    onboarding_ratings,
    predict_scores,
    recommend,
    top_k_positions,
)


def _ratings(seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    rows = [
        (u, i, int(rng.integers(1, 11)))
        for u in range(1, 31)
        for i in range(100, 116)
        if rng.random() < 0.6
    ]
    return pd.DataFrame(rows, columns=["user_id", "anime_id", "score"])


def _spark_model(spark, ratings: pd.DataFrame, implicit: bool, offset: float = 0.0):
    df = ratings.assign(score=ratings["score"].astype(float) - offset)
    als = ALS(
        rank=4,
        regParam=0.1,
        maxIter=15,
        implicitPrefs=implicit,
        alpha=0.5,
        userCol="user_id",
        itemCol="anime_id",
        ratingCol="score",
        seed=42,
    )
    fitted = als.fit(spark.createDataFrame(df))
    items = fitted.itemFactors.toPandas().sort_values("id")
    users = fitted.userFactors.toPandas().set_index("id")
    model = FoldInModel(
        item_ids=items["id"].to_numpy(),
        factors=np.vstack(items["features"].to_numpy()),
        reg_param=0.1,
        implicit=implicit,
        alpha=0.5,
        rating_offset=offset,
    )
    return model, users


@pytest.mark.parametrize(("implicit", "offset"), [(False, 0.0), (True, 5.0)])
def test_fold_in_matches_spark_user_factors(spark, implicit, offset):
    ratings = _ratings()
    model, users = _spark_model(spark, ratings, implicit, offset)
    for user_id, part in ratings.groupby("user_id"):
        vec = fold_in(model, part["anime_id"].to_numpy(), part["score"].to_numpy())
        # Jeu jouet tiré avec une seed fixe : chaque utilisateur a au moins une note > neutre,
        # sinon le fold-in implicite renverrait None (cas testé à part).
        assert vec is not None
        expected = np.asarray(users.loc[user_id, "features"])
        # Spark calcule en float32 : tolérance relative à la norme du vecteur.
        assert np.allclose(vec, expected, atol=1e-3 * max(1.0, np.linalg.norm(expected)))


def _toy_model(implicit: bool = False) -> FoldInModel:
    factors = np.array([[1.0, 0.0], [0.0, 1.0], [1.0, 1.0], [0.5, -0.5]])
    return FoldInModel(
        item_ids=np.array([10, 20, 30, 40]),
        factors=factors,
        reg_param=0.1,
        implicit=implicit,
        alpha=1.0,
        rating_offset=5.0 if implicit else 0.0,
    )


def test_unknown_items_are_ignored():
    model = _toy_model()
    with_unknown = fold_in(model, np.array([10, 999, 20]), np.array([8.0, 3.0, 6.0]))
    without = fold_in(model, np.array([10, 20]), np.array([8.0, 6.0]))
    assert np.allclose(with_unknown, without)


@pytest.mark.parametrize("implicit", [False, True])
def test_no_known_rating_returns_none(implicit):
    model = _toy_model(implicit)
    assert fold_in(model, np.array([999]), np.array([8.0])) is None
    assert fold_in(model, np.array([], dtype=int), np.array([])) is None


def test_implicit_without_positive_preference_returns_none():
    # Toutes les notes sous le neutre : aucune préférence positive, le vecteur serait nul.
    model = _toy_model(implicit=True)
    assert fold_in(model, np.array([10, 20]), np.array([2.0, 3.0])) is None


def test_mismatched_lengths_raise():
    with pytest.raises(ValueError, match="longueur"):
        fold_in(_toy_model(), np.array([10, 20]), np.array([8.0]))


def test_fold_in_is_deterministic():
    model = _toy_model()
    a = fold_in(model, np.array([10, 30]), np.array([9.0, 7.0]))
    b = fold_in(model, np.array([10, 30]), np.array([9.0, 7.0]))
    assert np.array_equal(a, b)


def test_onboarding_ratings_use_default_and_keep_explicit_scores():
    ids, scores = onboarding_ratings(choices=[10, 20, 30], scores={20: 4}, default_score=8)
    assert ids.tolist() == [10, 20, 30]
    assert scores.tolist() == [8.0, 4.0, 8.0]


def test_onboarding_rated_title_outside_choices_is_kept():
    ids, scores = onboarding_ratings(choices=[10], scores={40: 9}, default_score=8)
    assert sorted(zip(ids.tolist(), scores.tolist(), strict=True)) == [(10, 8.0), (40, 9.0)]


@pytest.mark.parametrize("bad", [0, 11])
def test_onboarding_rejects_out_of_range_scores(bad):
    with pytest.raises(ValueError, match="1 et 10"):
        onboarding_ratings(choices=[10], scores={20: bad}, default_score=8)


def test_recommend_ranks_by_score_and_excludes_seen():
    model = _toy_model()
    user = np.array([1.0, 0.2])
    # Scores : 10 → 1.0, 20 → 0.2, 30 → 1.2, 40 → 0.4
    assert recommend(model, user, exclude=[], k=3).tolist() == [30, 10, 40]
    assert recommend(model, user, exclude=[30], k=2).tolist() == [10, 40]


def test_recommend_k_larger_than_catalog():
    model = _toy_model()
    assert len(recommend(model, np.array([1.0, 0.0]), exclude=[10], k=50)) == 3


def test_recommend_everything_seen_returns_empty():
    model = _toy_model()
    assert recommend(model, np.array([1.0, 0.0]), exclude=[10, 20, 30, 40], k=5).size == 0


def test_top_k_ties_broken_by_catalog_order():
    # Ex æquo : l'ordre du catalogue départage, de façon identique partout (éval et service).
    assert top_k_positions(np.array([1.0, 2.0, 2.0, 2.0]), np.array([1]), 2).tolist() == [2, 3]


def test_duplicate_or_nan_ratings_are_rejected():
    model = _toy_model()
    with pytest.raises(ValueError, match="double"):
        fold_in(model, np.array([10, 10]), np.array([8.0, 9.0]))
    with pytest.raises(ValueError, match="NaN"):
        fold_in(model, np.array([10, 20]), np.array([8.0, np.nan]))


def test_onboarding_rejects_bad_default_score():
    with pytest.raises(ValueError, match="défaut"):
        onboarding_ratings(choices=[10], scores={}, default_score=0)


def test_implicit_neutral_rating_is_ignored():
    # Note = neutre → r = 0 : ni préférence ni confiance supplémentaire (comme Spark).
    model = _toy_model(implicit=True)
    with_neutral = fold_in(model, np.array([10, 20]), np.array([9.0, 5.0]))
    without = fold_in(model, np.array([10]), np.array([9.0]))
    assert np.allclose(with_neutral, without)


def test_predict_scores_clips_and_refuses_unknown_items():
    model = _toy_model()
    assert predict_scores(model, np.array([20.0, 0.0]), np.array([10, 20])).tolist() == [10.0, 1.0]
    with pytest.raises(ValueError, match="hors catalogue"):
        predict_scores(model, np.array([1.0, 0.0]), np.array([999]))
