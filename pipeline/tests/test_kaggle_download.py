"""Tests du téléchargement Kaggle, avec une fausse API (aucun appel réseau)."""

import hashlib
import json
from dataclasses import dataclass, field

import pytest

from tsuzuku_pipeline.ingestion.kaggle_download import DownloadError, download_dataset

DATASET = "owner/some-dataset"
CONTENTS = {"a.csv": b"x,y\n1,2\n", "b.csv": b"z\n3\n"}


@dataclass
class FakeFile:
    name: str
    total_bytes: int


@dataclass
class FakePage:
    files: list
    next_page_token: str = ""


@dataclass
class FakeApi:
    """Imite la partie de KaggleApi utilisée : liste paginée + téléchargement d'un fichier."""

    contents: dict
    pages: int = 1
    downloads: list = field(default_factory=list)
    corrupt: set = field(default_factory=set)
    forces: list = field(default_factory=list)

    def dataset_list_files(self, dataset, page_token=None, page_size=20):
        # Un fichier "html" parasite par page, pour vérifier qu'on l'ignore et qu'on pagine.
        items = [FakeFile(n, len(b)) for n, b in self.contents.items()]
        page = int(page_token or 0)
        chunk = items[page :: self.pages]
        nxt = str(page + 1) if page + 1 < self.pages else ""
        return FakePage([*chunk, FakeFile(f"html/{page}.zip", 1)], nxt)

    def dataset_download_file(
        self, dataset, file_name, path=None, force=False, quiet=True, licenses=(), unzip=False
    ):
        self.downloads.append(file_name)
        self.forces.append(force)
        target = path / file_name
        # Comme la vraie bibliothèque : sans force, un fichier déjà là est considéré à jour.
        if target.exists() and not force:
            return False
        data = self.contents[file_name]
        if file_name in self.corrupt:
            data = data[:-1]
        target.write_bytes(data)
        return True


def test_downloads_requested_files_and_writes_manifest(tmp_path):
    api = FakeApi(CONTENTS)
    manifest = download_dataset(DATASET, ["a.csv", "b.csv"], tmp_path, api=api)

    assert sorted(api.downloads) == ["a.csv", "b.csv"]
    assert (tmp_path / "a.csv").read_bytes() == CONTENTS["a.csv"]
    on_disk = json.loads((tmp_path / "manifest.json").read_text())
    assert on_disk == manifest
    assert manifest["dataset"] == DATASET
    assert manifest["files"]["a.csv"]["sha256"] == hashlib.sha256(CONTENTS["a.csv"]).hexdigest()
    assert manifest["files"]["b.csv"]["size"] == len(CONTENTS["b.csv"])


def test_skips_files_already_present_with_right_size(tmp_path):
    (tmp_path / "a.csv").write_bytes(CONTENTS["a.csv"])
    api = FakeApi(CONTENTS)
    download_dataset(DATASET, ["a.csv", "b.csv"], tmp_path, api=api)
    assert api.downloads == ["b.csv"]


def test_redownloads_truncated_file_without_disabling_resume(tmp_path):
    (tmp_path / "a.csv").write_bytes(b"x")  # fichier incomplet laissé par un essai précédent
    api = FakeApi(CONTENTS)
    download_dataset(DATASET, ["a.csv"], tmp_path, api=api)
    assert api.downloads == ["a.csv"]
    # force=False : la bibliothèque kaggle peut reprendre son fichier .kaggle-partial.
    assert api.forces == [False]


class OfflineApi:
    """Toute requête échoue : simule l'absence de réseau ou de jeton."""

    def dataset_list_files(self, *a, **k):
        raise ConnectionError("no network")

    def dataset_download_file(self, *a, **k):
        raise ConnectionError("no network")


def test_works_offline_when_manifest_matches_disk(tmp_path):
    first = download_dataset(DATASET, ["a.csv", "b.csv"], tmp_path, api=FakeApi(CONTENTS))
    again = download_dataset(DATASET, ["a.csv", "b.csv"], tmp_path, api=OfflineApi())
    assert again == first


def test_manifest_shortcut_ignored_if_file_changed(tmp_path):
    download_dataset(DATASET, ["a.csv"], tmp_path, api=FakeApi(CONTENTS))
    (tmp_path / "a.csv").write_bytes(b"truncated")
    with pytest.raises(DownloadError, match="slug"):
        download_dataset(DATASET, ["a.csv"], tmp_path, api=OfflineApi())


def test_manifest_shortcut_ignored_for_new_file(tmp_path):
    download_dataset(DATASET, ["a.csv"], tmp_path, api=FakeApi(CONTENTS))
    api = FakeApi(CONTENTS)
    download_dataset(DATASET, ["a.csv", "b.csv"], tmp_path, api=api)
    assert api.downloads == ["b.csv"]


def test_force_redownloads_everything(tmp_path):
    for name, data in CONTENTS.items():
        (tmp_path / name).write_bytes(data)
    api = FakeApi(CONTENTS)
    download_dataset(DATASET, list(CONTENTS), tmp_path, api=api, force=True)
    assert sorted(api.downloads) == sorted(CONTENTS)


def test_follows_pagination(tmp_path):
    api = FakeApi(CONTENTS, pages=2)
    download_dataset(DATASET, ["a.csv", "b.csv"], tmp_path, api=api)
    assert sorted(api.downloads) == ["a.csv", "b.csv"]


def test_unknown_file_raises(tmp_path):
    with pytest.raises(DownloadError, match=r"absent.*c\.csv"):
        download_dataset(DATASET, ["c.csv"], tmp_path, api=FakeApi(CONTENTS))


def test_size_mismatch_after_download_raises(tmp_path):
    api = FakeApi(CONTENTS, corrupt={"a.csv"})
    with pytest.raises(DownloadError, match="taille"):
        download_dataset(DATASET, ["a.csv"], tmp_path, api=api)


def test_auth_failure_gives_actionable_message_without_secret(tmp_path, monkeypatch):
    monkeypatch.setenv("KAGGLE_API_TOKEN", "KGAT_secret_value")

    class BrokenApi:
        def dataset_list_files(self, *a, **k):
            raise RuntimeError("401 Unauthorized token=KGAT_secret_value")

    with pytest.raises(DownloadError) as exc:
        download_dataset(DATASET, ["a.csv"], tmp_path, api=BrokenApi())
    message = str(exc.value)
    # Le message liste toutes les causes possibles (jeton, slug, réseau) sans fuiter le secret.
    assert "access_token" in message
    assert "slug" in message
    assert "RuntimeError" in message
    assert "KGAT_secret_value" not in message
    assert exc.value.__cause__ is None
