"""Export de l'artefact : une copie par run, empreinte vérifiée avant chargement."""

import pytest
from sklearn.dummy import DummyClassifier

from tsuzuku_pipeline.ml.drop.export import ArtifactError, load_artifact, save_artifact


def _model():
    return DummyClassifier(strategy="prior").fit([[0], [1]], [0, 1])


def test_each_run_keeps_its_own_copy_and_current_points_to_last(tmp_path):
    models = tmp_path / "models"
    first = save_artifact(_model(), {"run_id": "r1", "threshold": 0.2}, models)
    second = save_artifact(_model(), {"run_id": "r2", "threshold": 0.3}, models)

    assert (models / "runs" / "r1" / "drop_model.joblib").is_file()
    assert (models / "runs" / "r2" / "drop_model.json").is_file()
    assert first["artifact"] == "models/runs/r1/drop_model.joblib"
    assert len(second["artifact_sha256"]) == 64

    _, card = load_artifact(models)  # modèle « courant » = dernier run
    assert card["run_id"] == "r2" and card["threshold"] == 0.3
    _, old = load_artifact(models / "runs" / "r1")  # l'historique reste chargeable
    assert old["run_id"] == "r1"


def test_tampered_artifact_is_refused(tmp_path):
    models = tmp_path / "models"
    save_artifact(_model(), {"run_id": "r1"}, models)
    (models / "drop_model.joblib").write_bytes(b"pas le bon fichier")
    with pytest.raises(ArtifactError, match="sha256"):
        load_artifact(models)


def test_card_without_hash_is_refused(tmp_path):
    models = tmp_path / "models"
    save_artifact(_model(), {"run_id": "r1"}, models)
    (models / "drop_model.json").write_text('{"run_id": "r1"}', encoding="utf-8")
    with pytest.raises(ArtifactError, match="sha256"):
        load_artifact(models)
