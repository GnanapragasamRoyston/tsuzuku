import math

import numpy as np
import pandas as pd
import pytest
from tsuzuku_ml.fold_in import FoldInModel, fold_in, recommend

from tsuzuku_pipeline.ml.reco.evaluate import (
    evaluate_users,
    onboarding_profile,
    ranking_metrics,
    rmse,
    shrunk_item_means,
)


def test_ranking_metrics_perfect_and_empty():
    p, r, ndcg = ranking_metrics([1, 2, 3], {1, 2, 3}, k=3)
    assert (p, r, ndcg) == (1.0, 1.0, 1.0)
    assert ranking_metrics([4, 5, 6], {1}, k=3) == (0.0, 0.0, 0.0)


def test_ranking_metrics_hand_computed():
    # Pertinents : 2 et 9. Top-3 : [5, 2, 7] → 1 pertinent en position 2.
    p, r, ndcg = ranking_metrics([5, 2, 7], {2, 9}, k=3)
    assert p == pytest.approx(1 / 3)
    assert r == pytest.approx(1 / 2)
    dcg = 1 / math.log2(3)
    idcg = 1 / math.log2(2) + 1 / math.log2(3)
    assert ndcg == pytest.approx(dcg / idcg)


def test_ranking_metrics_short_list_counts_k_in_precision():
    # Moins de k recommandations (catalogue épuisé) : la précision reste divisée par k.
    p, _, _ = ranking_metrics([1], {1}, k=2)
    assert p == 0.5


def test_ranking_metrics_requires_relevant_items():
    with pytest.raises(ValueError, match="pertinent"):
        ranking_metrics([1], set(), k=1)


def test_rmse():
    assert rmse(np.array([1.0, 3.0]), np.array([2.0, 3.0])) == pytest.approx(math.sqrt(0.5))
    assert rmse(np.array([]), np.array([])) is None


def test_shrunk_item_means_pull_rare_items_to_global_mean():
    stats = pd.DataFrame({"anime_id": [1, 2], "sum": [40, 2], "count": [4, 1]})
    g = 42 / 5  # 8.4
    means = shrunk_item_means(stats, global_mean=g, shrinkage=4)
    assert means[1] == pytest.approx((40 + 4 * g) / 8)
    assert means[2] == pytest.approx((2 + 4 * g) / 5)


def _holdout() -> pd.DataFrame:
    # Utilisateur 1 : a vu 10 ; a masqué 30 (aimé) et 40 (pas aimé).
    # Utilisateur 2 : masqué seulement 20 avec une note faible → aucun pertinent.
    return pd.DataFrame(
        {
            "user_id": [1, 1, 1, 2, 2],
            "anime_id": [10, 30, 40, 10, 20],
            "score": [9, 9, 3, 8, 2],
            "masked": [False, True, True, False, True],
        }
    )


def _model() -> FoldInModel:
    return FoldInModel(
        item_ids=np.array([10, 20, 30, 40]),
        factors=np.eye(4),
        reg_param=0.1,
        implicit=False,
    )


def test_evaluate_users_with_constant_scorer():
    model = _model()
    popularity = np.array([4.0, 3.0, 2.0, 1.0])  # 10 > 20 > 30 > 40
    result = evaluate_users(
        _holdout(),
        model.item_ids,
        scorer=lambda ids, scores: popularity,
        ks=(1, 2),
        relevant_min_score=8,
    )
    # Utilisateur 1 : 10 exclu (vu) → top-2 = [20, 30] ; pertinent = {30}.
    assert result["users_ranked"] == 1
    assert result["users_without_relevant"] == 1
    assert result["at_k"]["1"]["precision"] == 0.0
    assert result["at_k"]["2"]["precision"] == pytest.approx(0.5)
    assert result["at_k"]["2"]["recall"] == pytest.approx(1.0)
    # Couverture à k=2 : animes recommandés au moins une fois / animes du catalogue.
    assert result["at_k"]["2"]["coverage"] == pytest.approx(2 / 4)


def test_evaluate_users_counts_fallback_and_rmse():
    model = _model()
    fallback = np.array([1.0, 1.0, 1.0, 1.0])
    result = evaluate_users(
        _holdout(),
        model.item_ids,
        scorer=lambda ids, scores: None,
        ks=(1,),
        relevant_min_score=8,
        fallback=fallback,
        predict=lambda ids, scores, targets: np.full(len(targets), 6.0),
    )
    # Seul l'utilisateur 1 est classé (le 2 n'a aucun pertinent) : 1 seul passage au fallback.
    assert result["users_fallback"] == 1
    # Toutes les notes masquées connues : 9, 3, 2 contre 6.
    assert result["rmse"] == pytest.approx(math.sqrt((9 + 9 + 16) / 3))
    assert result["rmse_ratings"] == 3


def test_evaluate_users_empty_holdout_counts_no_user():
    empty = _holdout().iloc[0:0]
    result = evaluate_users(empty, _model().item_ids, lambda i, s: None, (1,), 8)
    assert result["users_ranked"] == 0 and result["users_without_relevant"] == 0
    assert result["at_k"]["1"]["ndcg"] is None


def test_evaluate_users_ranking_matches_service_recommend():
    # Le top-K de l'évaluation doit être celui que le service renverrait (même règle, mêmes
    # ex æquo) : sinon on mesurerait autre chose que ce qui est servi.
    model = FoldInModel(
        item_ids=np.array([10, 20, 30, 40]),
        factors=np.array([[1.0, 0.0], [1.0, 0.0], [0.5, 0.5], [1.0, 0.0]]),
        reg_param=0.1,
        implicit=False,
    )
    holdout = pd.DataFrame(
        {"user_id": [1, 1, 1], "anime_id": [30, 20, 40], "score": [9, 9, 9],
         "masked": [False, True, True]}
    )  # fmt: skip
    seen_by_scorer = []

    def scorer(ids, scores):
        vec = fold_in(model, ids, scores)
        seen_by_scorer.append(recommend(model, vec, exclude=ids, k=1).tolist())
        return model.factors @ vec

    result = evaluate_users(holdout, model.item_ids, scorer, (1,), 8)
    # Ex æquo 10/20/40 : le service prend 10 (ordre du catalogue) → pas un pertinent → 0.
    assert seen_by_scorer == [[10]]
    assert result["at_k"]["1"]["precision"] == 0.0


def test_signal_column_hides_visible_ratings_but_keeps_them_excluded():
    holdout = pd.DataFrame(
        {"user_id": [1, 1, 1], "anime_id": [10, 20, 30], "score": [9, 9, 9],
         "masked": [False, False, True], "signal": [True, False, False]}
    )  # fmt: skip
    given = []

    def scorer(ids, scores):
        given.append(ids.tolist())
        return np.array([4.0, 3.0, 2.0, 1.0])

    result = evaluate_users(holdout, _model().item_ids, scorer, (1,), 8)
    assert given == [[10]]  # 20 n'est pas transmis…
    # …mais reste exclu : top-1 = 30 (10 et 20 vus), pertinent → précision 1.
    assert result["at_k"]["1"]["precision"] == 1.0


def test_onboarding_profile_keeps_n_liked_at_default_score():
    holdout = pd.DataFrame(
        {
            "user_id": [1, 1, 1, 1, 2, 2],
            "anime_id": [10, 20, 30, 40, 10, 20],
            "score": [9, 10, 4, 8, 9, 3],
            "masked": [False, False, False, True, False, True],
        }
    )
    profile, excluded = onboarding_profile(holdout, 2, relevant_min_score=8, default_score=8,
                                           seed=1)  # fmt: skip
    assert excluded == 1  # l'utilisateur 2 n'a qu'un anime aimé visible
    assert set(profile["user_id"]) == {1}
    given = profile[profile["signal"]]
    assert sorted(given["anime_id"]) == [10, 20] and set(given["score"]) == {8.0}
    # Les cibles masquées sont intactes.
    assert profile.loc[profile["masked"], "score"].tolist() == [8]
    again, _ = onboarding_profile(holdout, 2, 8, 8, seed=1)
    assert again.equals(profile)


def test_evaluate_users_ignores_masked_items_outside_catalog():
    holdout = pd.DataFrame(
        {
            "user_id": [1, 1, 1],
            "anime_id": [10, 30, 999],
            "score": [9, 9, 10],
            "masked": [False, True, True],
        }
    )
    result = evaluate_users(
        holdout,
        _model().item_ids,
        scorer=lambda ids, scores: np.array([0.0, 0.0, 1.0, 0.0]),
        ks=(1,),
        relevant_min_score=8,
    )
    # 999 n'est pas recommandable : seul 30 compte comme pertinent → rappel 1.
    assert result["at_k"]["1"]["recall"] == 1.0
    assert result["masked_outside_catalog"] == 1
