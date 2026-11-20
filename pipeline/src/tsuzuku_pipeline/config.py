"""Chargement de la configuration centrale (config/settings.yaml)."""

import os
from pathlib import Path
from typing import Any

import yaml

# Sections sans lesquelles aucun job du pipeline ne peut tourner : on échoue tôt et clairement
# plutôt que de laisser un KeyError obscur surgir au milieu d'un job Spark de 20 minutes.
REQUIRED_SECTIONS = ("project", "paths")

# Racine du dépôt : déduite de l'emplacement du code en développement. Dans l'image Airflow, le
# paquet est installé dans site-packages : TSUZUKU_ROOT indique où sont montés config/, data/ et
# reports/ (phase 6).
REPO_ROOT = Path(os.environ.get("TSUZUKU_ROOT") or Path(__file__).resolve().parents[3])
DEFAULT_SETTINGS_PATH = REPO_ROOT / "config" / "settings.yaml"


class ConfigError(Exception):
    """Configuration absente ou invalide."""


def load_settings(path: Path | str = DEFAULT_SETTINGS_PATH) -> dict[str, Any]:
    """Lit settings.yaml et vérifie la présence des sections obligatoires."""
    path = Path(path)
    if not path.is_file():
        raise ConfigError(f"Fichier de configuration introuvable : {path}")

    # safe_load : un YAML ne doit jamais pouvoir instancier d'objets Python arbitraires.
    with path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f)

    if not isinstance(data, dict):
        raise ConfigError(f"{path} doit contenir un dictionnaire YAML à la racine")

    missing = [s for s in REQUIRED_SECTIONS if s not in data]
    if missing:
        raise ConfigError(f"Sections manquantes dans {path} : {', '.join(missing)}")

    return data


def require_section(settings: dict[str, Any], name: str) -> dict[str, Any]:
    """Renvoie une section propre à une phase, ou échoue clairement si elle manque.

    Les sections de phase (data, drop_model, als...) ne sont pas dans REQUIRED_SECTIONS :
    chaque job vérifie seulement celle dont il a besoin.
    """
    section = settings.get(name)
    if not isinstance(section, dict):
        raise ConfigError(f"Section '{name}' absente ou invalide dans settings.yaml")
    return section


def resolve_path(settings: dict[str, Any], key: str) -> Path:
    """Chemin de settings.paths, rendu absolu par rapport à la racine du dépôt.

    Sans ça, `make data` lancé depuis pipeline/ écrirait dans pipeline/data au lieu de data/.
    """
    raw = settings.get("paths", {}).get(key)
    if raw is None:
        raise ConfigError(f"Chemin paths.{key} absent de settings.yaml")
    path = Path(raw)
    return path if path.is_absolute() else REPO_ROOT / path
