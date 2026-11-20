import numpy as np
import pandas as pd
from tsuzuku_ml.fold_in import FoldInModel

from tsuzuku_pipeline.ml.reco.train import (
    GridPoint,
    als_predictor,
    als_scorer,
    fit_als,
    grid_points,
    item_stats,
    popularity_scores,
    rating_offset,
)

CFG = {
    "ranks": [2, 4],
    "reg_params": [0.1],
    "max_iter": 5,
    "implicit_alpha": 1.0,
    "implicit_neutral_score": 5,
    "num_blocks": 2,
}


def test_grid_points_cover_both_kinds():
    points = list(grid_points(CFG))
    assert len(points) == 4
    assert {p.kind for p in points} == {"als_explicit", "als_implicit"}


def test_rating_offset_only_for_implicit():
    assert rating_offset(GridPoint("als_explicit", 2, 0.1), CFG) == 0.0
    assert rating_offset(GridPoint("als_implicit", 2, 0.1), CFG) == 5.0


def _ratings(spark):
    rng = np.random.default_rng(1)
    rows = [
        (u, i, int(rng.integers(1, 11)))
        for u in range(1, 21)
        for i in range(1, 11)
        if rng.random() < 0.7
    ]
    return spark.createDataFrame(rows, "user_id INT, anime_id INT, score INT")


def test_fit_als_returns_fold_in_model(spark):
    model = fit_als(_ratings(spark), GridPoint("als_implicit", 3, 0.1), CFG, seed=42)
    assert model.implicit and model.rating_offset == 5.0
    assert model.factors.shape[1] == 3
    assert sorted(model.item_ids.tolist()) == model.item_ids.tolist()


def test_fit_als_is_deterministic_with_same_seed(spark):
    # Même données, même seed → mêmes facteurs : un run est reproductible.
    point = GridPoint("als_explicit", 3, 0.1)
    a = fit_als(_ratings(spark), point, CFG, seed=7)
    b = fit_als(_ratings(spark), point, CFG, seed=7)
    assert np.array_equal(a.item_ids, b.item_ids)
    assert np.allclose(a.factors, b.factors)


def test_item_stats_and_popularity(spark):
    df = spark.createDataFrame(
        [(1, 10, 9), (2, 10, 8), (3, 10, 3), (1, 20, 8)], "user_id INT, anime_id INT, score INT"
    )
    stats = item_stats(df, relevant_min_score=8).set_index("anime_id")
    assert stats.loc[10, "count"] == 3 and stats.loc[10, "relevant"] == 2
    assert stats.loc[10, "sum"] == 20.0
    pop = popularity_scores(stats.reset_index(), np.array([20, 10, 30]))
    assert pop.tolist() == [1.0, 2.0, 0.0]  # 30 inconnu → 0


def _model():
    return FoldInModel(
        item_ids=np.array([10, 20]), factors=np.eye(2), reg_param=0.1, implicit=False
    )


def test_scorer_returns_none_without_known_items():
    assert als_scorer(_model())(np.array([999]), np.array([8.0])) is None
    assert als_scorer(_model())(np.array([10]), np.array([8.0])).shape == (2,)


def test_predictor_falls_back_to_item_means():
    means = pd.Series({10: 7.0, 20: 6.5})
    pred = als_predictor(_model(), means)(np.array([999]), np.array([8.0]), np.array([20, 10]))
    assert pred.tolist() == [6.5, 7.0]
