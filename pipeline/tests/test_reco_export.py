import json

import numpy as np
import pytest
from tsuzuku_ml.fold_in import FoldInModel, fold_in

from tsuzuku_pipeline.ml.drop.export import ArtifactError
from tsuzuku_pipeline.ml.reco.export import (
    load_reco_model,
    reco_paths,
    save_reco_artifact,
    verify_reco_artifact,
)


def _model():
    return FoldInModel(
        item_ids=np.array([10, 20, 30]),
        factors=np.array([[1.0, 0.5], [0.0, 1.0], [0.25, -1.0]]),
        reg_param=0.1,
        implicit=True,
        alpha=2.0,
        rating_offset=5.0,
    )


def test_round_trip_keeps_fold_in_identical(tmp_path):
    models = tmp_path / "models"
    card = save_reco_artifact(_model(), {"run_id": "r1"}, models)
    assert card["artifact"] == "models/runs/r1/reco_item_factors.parquet"
    loaded, loaded_card = load_reco_model(models)
    assert loaded_card["fold_in"]["implicit"] is True
    ids, scores = np.array([10, 30]), np.array([9.0, 3.0])
    # Facteurs stockés en float32 : écart négligeable.
    assert np.allclose(fold_in(loaded, ids, scores), fold_in(_model(), ids, scores), atol=1e-6)


def test_run_copy_is_kept(tmp_path):
    models = tmp_path / "models"
    save_reco_artifact(_model(), {"run_id": "r1"}, models)
    save_reco_artifact(_model(), {"run_id": "r2"}, models)
    assert all(p.is_file() for p in reco_paths(models / "runs" / "r1"))
    assert json.loads(reco_paths(models)[1].read_text())["run_id"] == "r2"


def test_tampered_factors_are_refused(tmp_path):
    models = tmp_path / "models"
    save_reco_artifact(_model(), {"run_id": "r1"}, models)
    factors, _ = reco_paths(models)
    factors.write_bytes(factors.read_bytes() + b"x")
    with pytest.raises(ArtifactError, match="sha256"):
        verify_reco_artifact(models)


def _rewrite_card(models, **changes):
    """Modifie la fiche ET recalcule rien : simule une fiche cohérente (sha256 OK) mais fausse."""
    _, card_path = reco_paths(models)
    card = json.loads(card_path.read_text())
    card.update(changes)
    card_path.write_text(json.dumps(card))


def test_wrong_schema_version_is_refused(tmp_path):
    models = tmp_path / "models"
    save_reco_artifact(_model(), {"run_id": "r1"}, models)
    _rewrite_card(models, schema_version=99)
    with pytest.raises(ArtifactError, match="schema_version"):
        load_reco_model(models)


def test_shape_mismatch_is_refused(tmp_path):
    models = tmp_path / "models"
    save_reco_artifact(_model(), {"run_id": "r1"}, models)
    _rewrite_card(models, n_items=5)
    with pytest.raises(ArtifactError, match="attendu"):
        load_reco_model(models)


def test_missing_artifact_is_refused(tmp_path):
    with pytest.raises(ArtifactError, match="incomplet"):
        verify_reco_artifact(tmp_path)
