"""Entraînement du modèle de drop sur des données synthétiques au signal connu."""

import numpy as np
import pandas as pd
import pytest

from tsuzuku_pipeline.ml.drop.features import FORBIDDEN_COLUMNS, feature_columns
from tsuzuku_pipeline.ml.drop.train import (
    build_pipeline,
    calibrate_isotonic,
    choose_threshold,
    expand_grid,
    prepare_x,
    select_models,
    split_by_user,
)

GENRES = ["Action", "Drama"]
CFG = {
    "val_fraction": 0.2,
    "test_fraction": 0.2,
    "top_studios": 3,
    "logreg": {"C": [1.0], "max_iter": 500},
    "hgb": {"learning_rate": [0.1], "max_leaf_nodes": [15], "max_iter": 50},
    "calibration": "none",
}


def synthetic(n_users=400, per_user=12, seed=0):
    """Le drop dépend du taux de drop historique de l'utilisateur et de l'affinité de genre."""
    rng = np.random.default_rng(seed)
    rows = []
    for u in range(n_users):
        taste = rng.uniform(0, 0.6)
        for a in range(per_user):
            affinity = rng.uniform(0, 1)
            p = 1 / (1 + np.exp(-(-3 + 5 * taste - 2 * affinity)))
            rows.append(
                {
                    "user_id": u,
                    "anime_id": a,
                    "is_dropped": int(rng.uniform() < p),
                    "format": rng.choice(["TV", "Movie", None]),
                    "source": rng.choice(["Manga", "Original"]),
                    "age_rating": "PG-13",
                    "main_studio": rng.choice(["S1", "S2", "S3", "S4", "S5", None]),
                    "episodes": rng.choice([12, 24, np.nan]),
                    "duration_min": 24.0,
                    "start_year": 2010,
                    "popularity": int(rng.integers(1, 5000)),
                    "genre_action": int(rng.integers(0, 2)),
                    "genre_drama": int(rng.integers(0, 2)),
                    "user_list_size": per_user - 1,
                    "user_cd_count": per_user - 1,
                    "user_drop_rate": taste + rng.normal(0, 0.05),
                    "user_mean_score": rng.choice([7.5, np.nan]),
                    "genre_affinity": affinity,
                    "user_share_action": rng.uniform(),
                    "user_share_drama": rng.uniform(),
                    # Colonne interdite présente dans les données brutes : ne doit jamais entrer.
                    "score": 0,
                }
            )
    return pd.DataFrame(rows)


@pytest.fixture(scope="module")
def data():
    return synthetic()


def test_split_by_user_has_no_overlap_and_is_deterministic(data):
    s1 = split_by_user(data, 0.2, 0.2, seed=42)
    s2 = split_by_user(data, 0.2, 0.2, seed=42)
    users = [set(part.user_id) for part in (s1.train, s1.val, s1.test)]
    assert not users[0] & users[1] and not users[0] & users[2] and not users[1] & users[2]
    assert len(s1.train) + len(s1.val) + len(s1.test) == len(data)
    assert len(s1.test) / len(data) == pytest.approx(0.2, abs=0.05)
    assert s1.test.index.equals(s2.test.index)


def test_prepare_x_keeps_only_model_features(data):
    x = prepare_x(data, GENRES)
    assert list(x.columns) == feature_columns(GENRES)
    assert not set(x.columns) & FORBIDDEN_COLUMNS
    assert x["episodes"].dtype == np.float32


@pytest.mark.parametrize("kind", ["dummy", "logreg", "hgb"])
def test_pipeline_handles_missing_and_unknown_categories(data, kind):
    params = {
        "dummy": {},
        "logreg": {"C": 1.0, "max_iter": 200},
        "hgb": {"learning_rate": 0.1, "max_leaf_nodes": 15, "max_iter": 20},
    }[kind]
    pipe = build_pipeline(kind, params, GENRES, top_studios=3, seed=0)
    pipe.fit(prepare_x(data, GENRES), data["is_dropped"])
    unseen = data.head(5).copy()
    unseen["main_studio"] = "Studio jamais vu"
    unseen["format"] = None
    proba = pipe.predict_proba(prepare_x(unseen, GENRES))[:, 1]
    assert np.all((proba >= 0) & (proba <= 1))
    # Le pipeline final ne voit jamais de colonne interdite.
    assert not set(pipe.feature_names_in_) & FORBIDDEN_COLUMNS


def test_expand_grid():
    grid = expand_grid({"learning_rate": [0.05, 0.1], "max_leaf_nodes": [31], "max_iter": 300})
    assert grid == [
        {"learning_rate": 0.05, "max_leaf_nodes": 31, "max_iter": 300},
        {"learning_rate": 0.1, "max_leaf_nodes": 31, "max_iter": 300},
    ]


def test_select_models_beats_baseline(data):
    split = split_by_user(data, 0.2, 0.2, seed=42)
    best = select_models(split, CFG, GENRES, seed=42)
    assert set(best) == {"dummy", "logreg", "hgb"}
    base = best["dummy"].val_pr_auc
    assert best["logreg"].val_pr_auc > base + 0.05
    assert best["hgb"].val_pr_auc > base + 0.05


def test_calibrate_isotonic_uses_disjoint_halves(data):
    split = split_by_user(data, 0.2, 0.2, seed=42)
    pipe = build_pipeline(
        "hgb", {"learning_rate": 0.1, "max_leaf_nodes": 15, "max_iter": 30}, GENRES, 3, seed=0
    )
    pipe.fit(prepare_x(split.train, GENRES), split.train["is_dropped"])
    model, thr = calibrate_isotonic(pipe, split.val, GENRES, seed=42)
    proba = model.predict_proba(prepare_x(thr, GENRES))[:, 1]
    assert np.all((proba >= 0) & (proba <= 1))
    assert 0 < len(thr) < len(split.val)
    assert set(thr.user_id) <= set(split.val.user_id)


def test_choose_threshold_maximizes_f1():
    y = np.array([0, 0, 0, 1, 1])
    p = np.array([0.1, 0.2, 0.35, 0.4, 0.9])
    # Seuil 0.4 : 2 vrais positifs, 0 faux positif → F1 = 1.
    assert choose_threshold(y, p) == pytest.approx(0.4)
