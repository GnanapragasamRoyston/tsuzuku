"""Tests du chargement de config/settings.yaml."""

from pathlib import Path

import pytest

from tsuzuku_pipeline.config import ConfigError, load_settings

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_loads_real_settings_file():
    # Le vrai fichier du dépôt doit toujours rester chargeable : sinon la CI casse tôt.
    settings = load_settings(REPO_ROOT / "config" / "settings.yaml")
    assert settings["project"]["seed"] == 42
    assert "raw" in settings["paths"]


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
