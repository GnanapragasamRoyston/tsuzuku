"""Métriques, calibration, importance par permutation et figures du modèle de drop."""

import numpy as np
import pytest
from test_drop_train import GENRES, synthetic

from tsuzuku_pipeline.ml.drop.evaluate import (
    classification_metrics,
    permutation_ranking,
    plot_calibration,
    plot_curves,
    plot_importance,
    reliability,
)
from tsuzuku_pipeline.ml.drop.train import build_pipeline, prepare_x


def test_classification_metrics_on_known_case():
    y = np.array([0, 0, 0, 0, 1, 1])
    p = np.array([0.1, 0.2, 0.3, 0.6, 0.7, 0.9])
    m = classification_metrics(y, p, threshold=0.5)
    # Seuil 0.5 : prédits drop = {0.6, 0.7, 0.9} → TP 2, FP 1, FN 0, TN 3.
    assert m["confusion"] == {"tn": 3, "fp": 1, "fn": 0, "tp": 2}
    assert m["precision"] == pytest.approx(2 / 3)
    assert m["recall"] == pytest.approx(1.0)
    assert m["f1"] == pytest.approx(0.8)
    assert m["roc_auc"] == pytest.approx(1.0)
    assert m["prevalence"] == pytest.approx(2 / 6)
    assert 0 <= m["brier"] <= 1
    assert set(m) >= {"pr_auc", "log_loss", "ece", "threshold", "n"}


def test_reliability_bins_cover_all_rows_and_ece_zero_when_perfect():
    rng = np.random.default_rng(0)
    p = rng.uniform(size=20000)
    y = (rng.uniform(size=20000) < p).astype(int)  # parfaitement calibré par construction
    bins, ece = reliability(y, p, n_bins=10)
    assert sum(b["n"] for b in bins) == 20000
    assert ece < 0.02
    biased_bins, biased_ece = reliability(y, np.clip(p + 0.2, 0, 1), n_bins=10)
    assert biased_ece > 0.1


def test_ece_of_constant_prediction_is_not_zero():
    # Baseline : une seule probabilité → un seul bin. Revue Fable : l'ECE sortait à 0.0 (faux).
    y = np.array([0] * 94 + [1] * 6)
    p = np.full(100, 0.0572)
    bins, ece = reliability(y, p)
    assert ece == pytest.approx(abs(0.0572 - 0.06))
    assert bins == [{"mean_pred": pytest.approx(0.0572), "observed": 0.06, "n": 100}]


def test_plot_calibration_handles_single_bin(tmp_path):
    plot_calibration([{"mean_pred": 0.05, "observed": 0.06, "n": 10}], "hgb", tmp_path / "c.png")
    assert (tmp_path / "c.png").is_file()


@pytest.fixture(scope="module")
def fitted():
    df = synthetic(n_users=200, per_user=10)
    pipe = build_pipeline(
        "hgb", {"learning_rate": 0.1, "max_leaf_nodes": 15, "max_iter": 30}, GENRES, 3, seed=0
    )
    pipe.fit(prepare_x(df, GENRES), df["is_dropped"])
    return pipe, df


def test_permutation_ranking_finds_the_true_signal(fitted):
    pipe, df = fitted
    ranking = permutation_ranking(
        pipe, prepare_x(df, GENRES), df["is_dropped"], n_rows=1000, n_repeats=3, seed=0
    )
    # Les données synthétiques ne dépendent que de ces deux features : elles doivent sortir en tête.
    assert {r["feature"] for r in ranking[:2]} == {"user_drop_rate", "genre_affinity"}
    assert ranking == sorted(ranking, key=lambda r: -r["importance"])


def test_figures_are_written(tmp_path, fitted):
    pipe, df = fitted
    y = df["is_dropped"].to_numpy()
    p = pipe.predict_proba(prepare_x(df, GENRES))[:, 1]
    curves = {"dummy": np.full_like(p, y.mean()), "hgb": p}
    plot_curves(y, curves, tmp_path)
    bins, _ = reliability(y, p)
    plot_calibration(bins, "hgb", tmp_path / "calibration.png")
    plot_importance(
        [{"feature": "user_drop_rate", "importance": 0.2, "std": 0.01}],
        tmp_path / "importance.png",
    )
    for name in ["roc.png", "pr.png", "calibration.png", "importance.png"]:
        assert (tmp_path / name).stat().st_size > 1000
