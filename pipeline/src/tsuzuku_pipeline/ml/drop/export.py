"""Sauvegarde du modèle de drop : artefact joblib + fiche modèle JSON.

⚠️ joblib = pickle : charger un artefact exécute du code. On ne charge donc que NOS artefacts,
produits par `make train`, et seulement si leur sha256 correspond à celui de la fiche.

Organisation :
- models/runs/<run_id>/drop_model.{joblib,json} : une copie par run, jamais écrasée → chaque
  ligne de mart.model_runs pointe vers un fichier qui existe encore ;
- models/drop_model.{joblib,json} : le modèle « courant », que l'API chargera.
"""

import hashlib
import json
import os
import shutil
from pathlib import Path
from typing import Any

import joblib

ARTIFACT_NAME = "drop_model"


class ArtifactError(Exception):
    """Artefact absent, incomplet ou différent de ce que décrit sa fiche."""


def artifact_paths(models_dir: Path, name: str = ARTIFACT_NAME) -> tuple[Path, Path]:
    return models_dir / f"{name}.joblib", models_dir / f"{name}.json"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(1 << 20):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_copy(src: Path, dst: Path) -> None:
    # Copie vers un fichier temporaire puis os.replace (atomique sur un même disque) : un lecteur
    # voit l'ancien ou le nouveau fichier, jamais un fichier à moitié écrit.
    tmp = dst.with_suffix(dst.suffix + ".tmp")
    shutil.copyfile(src, tmp)
    os.replace(tmp, dst)


def save_artifact(model: Any, card: dict[str, Any], models_dir: Path) -> dict[str, Any]:
    """Écrit la copie du run, puis remplace le modèle courant. Renvoie la fiche complétée."""
    run_dir = models_dir / "runs" / card["run_id"]
    run_dir.mkdir(parents=True, exist_ok=True)
    run_model, run_card = artifact_paths(run_dir)
    joblib.dump(model, run_model)

    card = {
        **card,
        "artifact": run_model.relative_to(models_dir.parent).as_posix(),
        "artifact_sha256": _sha256(run_model),
    }
    run_card.write_text(json.dumps(card, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    current_model, current_card = artifact_paths(models_dir)
    # Modèle d'abord, fiche en dernier : si on s'arrête entre les deux, l'empreinte de l'ancienne
    # fiche ne correspond plus au fichier et load_artifact refuse de charger (pas de mélange).
    _atomic_copy(run_model, current_model)
    _atomic_copy(run_card, current_card)
    return card


def verify_artifact(models_dir: Path) -> dict[str, Any]:
    """Vérifie que le modèle correspond à sa fiche (sha256), SANS le désérialiser."""
    model_path, card_path = artifact_paths(models_dir)
    if not card_path.is_file() or not model_path.is_file():
        raise ArtifactError(f"Artefact incomplet dans {models_dir}")
    card = json.loads(card_path.read_text(encoding="utf-8"))
    expected = card.get("artifact_sha256")
    if not expected or _sha256(model_path) != expected:
        raise ArtifactError(
            f"{model_path.name} : sha256 absent de la fiche ou différent ; chargement refusé"
        )
    return card


def load_artifact(models_dir: Path) -> tuple[Any, dict[str, Any]]:
    card = verify_artifact(models_dir)
    model_path, _ = artifact_paths(models_dir)
    # nosec B301 : fichier produit par ce projet ET dont l'empreinte vient d'être vérifiée.
    return joblib.load(model_path), card
