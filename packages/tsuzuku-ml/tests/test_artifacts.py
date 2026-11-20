import json

import joblib
import numpy as np
import pandas as pd
import pytest
import sklearn
from sklearn.dummy import DummyClassifier
from tsuzuku_ml.artifacts import (
    RECO_SCHEMA_VERSION,
    ArtifactError,
    check_reco_parity,
    drop_paths,
    load_drop_model,
    load_reco_model,
    reco_paths,
    sha256_file,
)
from tsuzuku_ml.fold_in import FoldInModel, fold_in, recommend


def _write_drop(models, versions=None):
    models.mkdir(parents=True, exist_ok=True)
    model_path, card_path = drop_paths(models)
    joblib.dump(DummyClassifier(strategy="prior").fit([[0], [1]], [0, 1]), model_path)
    card = {"artifact_sha256": sha256_file(model_path),
            "versions": versions or {"scikit-learn": sklearn.__version__}}  # fmt: skip
    card_path.write_text(json.dumps(card))


def test_drop_model_loads_when_hash_and_version_match(tmp_path):
    _write_drop(tmp_path)
    model, card = load_drop_model(tmp_path)
    assert model.predict_proba([[0]]).shape == (1, 2)


def test_drop_model_refused_with_other_sklearn_minor(tmp_path):
    _write_drop(tmp_path, versions={"scikit-learn": "1.2.0"})
    with pytest.raises(ArtifactError, match="scikit-learn"):
        load_drop_model(tmp_path)


def test_drop_model_refused_when_tampered(tmp_path):
    _write_drop(tmp_path)
    model_path, _ = drop_paths(tmp_path)
    model_path.write_bytes(model_path.read_bytes() + b"x")
    with pytest.raises(ArtifactError, match="sha256"):
        load_drop_model(tmp_path)


def _model():
    return FoldInModel(
        item_ids=np.array([10, 20, 30, 40]),
        factors=np.array([[1.0, 0.0], [0.0, 1.0], [1.0, 1.0], [0.5, -0.5]]),
        reg_param=0.1,
        implicit=True,
        alpha=1.0,
        rating_offset=5.0,
    )


def _write_reco(models, model, **card_changes):
    models.mkdir(parents=True, exist_ok=True)
    factors_path, card_path = reco_paths(models)
    pd.DataFrame({"anime_id": model.item_ids, "factors": list(model.factors)}).to_parquet(
        factors_path, index=False
    )
    vec = fold_in(model, np.array([10]), np.array([9.0]))
    card = {
        "schema_version": RECO_SCHEMA_VERSION,
        "n_items": len(model.item_ids),
        "fold_in": {"rank": model.rank, "reg_param": model.reg_param, "implicit": True,
                    "alpha": 1.0, "rating_offset": 5.0},
        "artifact_sha256": sha256_file(factors_path),
        "parity_check": {"anime_ids": [10], "scores": [9.0],
                         "expected_top10": recommend(model, vec, exclude=[10], k=3).tolist()},
        **card_changes,
    }  # fmt: skip
    card_path.write_text(json.dumps(card))


def test_reco_model_round_trip_passes_parity_check(tmp_path):
    _write_reco(tmp_path, _model())
    model, card = load_reco_model(tmp_path)
    check_reco_parity(model, card)  # ne lève pas


def test_parity_check_detects_a_different_model(tmp_path):
    _write_reco(tmp_path, _model(), parity_check={"anime_ids": [10], "scores": [9.0],
                                                  "expected_top10": [40, 30, 20]})  # fmt: skip
    model, card = load_reco_model(tmp_path)
    with pytest.raises(ArtifactError, match="parity_check"):
        check_reco_parity(model, card)


def test_parity_check_missing_is_refused(tmp_path):
    _write_reco(tmp_path, _model(), parity_check={})
    model, card = load_reco_model(tmp_path)
    with pytest.raises(ArtifactError, match="absent"):
        check_reco_parity(model, card)


def test_reco_wrong_schema_is_refused(tmp_path):
    _write_reco(tmp_path, _model(), schema_version=2)
    with pytest.raises(ArtifactError, match="schema_version"):
        load_reco_model(tmp_path)
