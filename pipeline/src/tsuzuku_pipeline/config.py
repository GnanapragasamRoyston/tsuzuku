"""Chargement de la configuration centrale (config/settings.yaml)."""

from pathlib import Path
from typing import Any

import yaml

# Sections sans lesquelles aucun job du pipeline ne peut tourner : on échoue tôt et clairement
# plutôt que de laisser un KeyError obscur surgir au milieu d'un job Spark de 20 minutes.
REQUIRED_SECTIONS = ("project", "paths")

DEFAULT_SETTINGS_PATH = Path(__file__).resolve().parents[3] / "config" / "settings.yaml"


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
