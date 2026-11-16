"""Tests du chargement de config/settings.yaml."""

from pathlib import Path

import pytest

from tsuzuku_pipeline.config import ConfigError, load_settings, require_section, resolve_path

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_loads_real_settings_file():
    # Le vrai fichier du dépôt doit toujours rester chargeable : sinon la CI casse tôt.
    settings = load_settings(REPO_ROOT / "config" / "settings.yaml")
    assert settings["project"]["seed"] == 42
    assert "raw" in settings["paths"]


def test_real_settings_has_phase1_data_section():
    settings = load_settings(REPO_ROOT / "config" / "settings.yaml")
    data = require_section(settings, "data")
    assert data["kaggle_dataset"] == "hernan4444/anime-recommendation-database-2020"
    assert "animelist.csv" in data["files"]
    assert 0 < data["sample_user_fraction"] < 1
    assert data["adult_filter"]["rating_prefixes"] == ["Rx"]


def test_require_section_raises_on_missing():
    with pytest.raises(ConfigError, match="data"):
        require_section({"project": {}}, "data")


def test_resolve_path_relative_to_repo_root():
    settings = {"paths": {"raw": "data/raw"}}
    assert resolve_path(settings, "raw") == REPO_ROOT / "data" / "raw"


def test_resolve_path_keeps_absolute(tmp_path):
    settings = {"paths": {"raw": str(tmp_path)}}
    assert resolve_path(settings, "raw") == tmp_path


def test_resolve_path_unknown_key():
    with pytest.raises(ConfigError, match="paths.nope"):
        resolve_path({"paths": {}}, "nope")


def test_missing_file_raises_clear_error(tmp_path):
    with pytest.raises(ConfigError, match="introuvable"):
        load_settings(tmp_path / "nope.yaml")


def test_missing_required_section_raises(tmp_path):
    path = tmp_path / "settings.yaml"
    path.write_text("project:\n  seed: 1\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="paths"):
        load_settings(path)


def test_non_mapping_yaml_raises(tmp_path):
    path = tmp_path / "settings.yaml"
    path.write_text("- juste\n- une liste\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="dictionnaire"):
        load_settings(path)
