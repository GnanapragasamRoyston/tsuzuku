"""Modèles téléchargés depuis Cloud Storage au démarrage de l'API (phase 11, ADR 014).

Faux client : aucun appel réseau. L'intégrité reste vérifiée ensuite par le chargement habituel
(sha256 de la fiche) ; ce module ne fait que copier les 4 fichiers attendus.
"""

import pytest

from app.core import model_store


class FakeBlob:
    def __init__(self, store, name):
        self.store, self.name = store, name

    def download_to_filename(self, path):
        if self.name not in self.store.files:
            raise FileNotFoundError(self.name)
        self.store.downloaded.append(self.name)
        with open(path, "wb") as f:
            f.write(self.store.files[self.name])


class FakeBucket:
    def __init__(self, store):
        self.store = store

    def blob(self, name):
        return FakeBlob(self.store, name)


class FakeClient:
    def __init__(self, files):
        self.files, self.downloaded, self.buckets = files, [], []

    def bucket(self, name):
        self.buckets.append(name)
        return FakeBucket(self)


def test_downloads_exactly_the_four_served_files(tmp_path):
    files = {f"models/{n}": n.encode() for n in model_store.MODEL_FILES}
    files["models/runs/old.joblib"] = b"historique : jamais servi"
    client = FakeClient(files)
    paths = model_store.download_models("gs://tsuzuku-models/models", tmp_path, client)
    assert client.buckets == ["tsuzuku-models"]
    assert sorted(p.name for p in paths) == sorted(model_store.MODEL_FILES)
    assert (tmp_path / "reco_model.json").read_bytes() == b"reco_model.json"
    assert not (tmp_path / "runs").exists()


def test_bucket_root_without_prefix(tmp_path):
    client = FakeClient({n: b"x" for n in model_store.MODEL_FILES})
    model_store.download_models("gs://bucket", tmp_path, client)
    assert sorted(client.downloaded) == sorted(model_store.MODEL_FILES)


@pytest.mark.parametrize("uri", ["s3://bucket/models", "gs://", "models", "gs:///x"])
def test_only_gs_uris_are_accepted(tmp_path, uri):
    with pytest.raises(ValueError):
        model_store.download_models(uri, tmp_path, FakeClient({}))


def test_a_missing_file_is_an_error_not_a_silent_partial_copy(tmp_path):
    client = FakeClient({"m/reco_model.json": b"x"})
    with pytest.raises(FileNotFoundError):
        model_store.download_models("gs://b/m", tmp_path, client)


def test_a_failed_download_leaves_the_current_models_untouched(tmp_path):
    """Copie atomique : tout ou rien (jamais un mélange d'anciens et de nouveaux fichiers)."""
    for name in model_store.MODEL_FILES:
        (tmp_path / name).write_bytes(b"ancien")
    files = {f"m/{n}": b"nouveau" for n in model_store.MODEL_FILES[:2]}  # les 2 suivants manquent
    with pytest.raises(FileNotFoundError):
        model_store.download_models("gs://b/m", tmp_path, FakeClient(files))
    assert all((tmp_path / n).read_bytes() == b"ancien" for n in model_store.MODEL_FILES)
