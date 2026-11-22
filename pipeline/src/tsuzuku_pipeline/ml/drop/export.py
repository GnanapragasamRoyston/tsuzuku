"""Sauvegarde du modèle de drop : artefact joblib + fiche modèle JSON.

Vérification et chargement vivent dans le paquet partagé (tsuzuku_ml.artifacts) : le pipeline et
l'API appliquent les mêmes contrôles (sha256, version de scikit-learn).
- models/runs/<run_id>/drop_model.{joblib,json} : une copie par run, jamais écrasée ;
- models/drop_model.{joblib,json} : le modèle « courant », que l'API charge.
"""

import json
from pathlib import Path
from typing import Any

import joblib
from tsuzuku_ml.artifacts import (  # noqa: F401  (ré-exportés pour le pipeline et ses tests)
    ArtifactError,
    atomic_copy,
    load_drop_model,
    sha256_file,
    verify_drop_artifact,
)
from tsuzuku_ml.artifacts import drop_paths as artifact_paths

# Noms historiques (phase 3), gardés pour ne pas casser les appelants.
verify_artifact = verify_drop_artifact
load_artifact = load_drop_model


def save_artifact(model: Any, card: dict[str, Any], models_dir: Path) -> dict[str, Any]:
    """Écrit la copie du run, puis remplace le modèle courant. Renvoie la fiche complétée."""
    run_dir = models_dir / "runs" / card["run_id"]
    run_dir.mkdir(parents=True, exist_ok=True)
    run_model, run_card = artifact_paths(run_dir)
    joblib.dump(model, run_model)

    card = {
        **card,
        "artifact": run_model.relative_to(models_dir.parent).as_posix(),
        "artifact_sha256": sha256_file(run_model),
    }
    run_card.write_text(json.dumps(card, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    current_model, current_card = artifact_paths(models_dir)
    # Modèle d'abord, fiche en dernier : si on s'arrête entre les deux, l'empreinte de l'ancienne
    # fiche ne correspond plus au fichier et le chargement est refusé (pas de mélange).
    atomic_copy(run_model, current_model)
    atomic_copy(run_card, current_card)
    return card
