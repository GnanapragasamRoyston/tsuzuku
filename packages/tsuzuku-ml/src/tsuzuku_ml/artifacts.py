"""Artefacts des modèles : chemins, empreintes, vérification et chargement.

Partagé par le pipeline (qui écrit les artefacts) et l'API (qui les charge) : les deux côtés
appliquent EXACTEMENT les mêmes contrôles.

Organisation dans models/ :
- runs/<run_id>/… : une copie par run, jamais écrasée (chaque ligne de mart.model_runs pointe
  vers un fichier qui existe encore) ;
- à la racine : le modèle « courant », que l'API charge.

⚠️ Le modèle de drop est un joblib = pickle : le charger exécute du code. On ne charge que NOS
artefacts, et seulement si leur sha256 correspond à celui de la fiche. Le sha256 prouve
l'INTÉGRITÉ (le fichier n'a pas changé), pas l'authenticité.
"""

import hashlib
import json
import os
import shutil
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
import sklearn

from tsuzuku_ml.fold_in import FoldInModel, fold_in, recommend

DROP_NAME = "drop_model"
RECO_FACTORS, RECO_CARD = "reco_item_factors.parquet", "reco_model.json"
# Contrat du modèle de reco lu par l'API : à incrémenter si le format change.
RECO_SCHEMA_VERSION = 1


class ArtifactError(Exception):
    """Artefact absent, incomplet, ou différent de ce que décrit sa fiche."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(1 << 20):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_copy(src: Path, dst: Path) -> None:
    # Copie vers un fichier temporaire puis os.replace (atomique sur un même disque) : un lecteur
    # voit l'ancien ou le nouveau fichier, jamais un fichier à moitié écrit.
    tmp = dst.with_suffix(dst.suffix + ".tmp")
    shutil.copyfile(src, tmp)
    os.replace(tmp, dst)


def _verified_card(artifact: Path, card_path: Path) -> dict[str, Any]:
    if not artifact.is_file() or not card_path.is_file():
        raise ArtifactError(f"Artefact incomplet dans {artifact.parent}")
    card = json.loads(card_path.read_text(encoding="utf-8"))
    expected = card.get("artifact_sha256")
    if not expected or sha256_file(artifact) != expected:
        raise ArtifactError(
            f"{artifact.name} : sha256 absent de la fiche ou différent ; chargement refusé"
        )
    return card


# --- Modèle de drop (scikit-learn, joblib) -----------------------------------------------------


def drop_paths(models_dir: Path, name: str = DROP_NAME) -> tuple[Path, Path]:
    return models_dir / f"{name}.joblib", models_dir / f"{name}.json"


def verify_drop_artifact(models_dir: Path) -> dict[str, Any]:
    """Vérifie que le modèle correspond à sa fiche (sha256), SANS le désérialiser."""
    return _verified_card(*drop_paths(models_dir))


def _minor(version: str) -> tuple[str, ...]:
    return tuple(version.split(".")[:2])


def load_drop_model(models_dir: Path) -> tuple[Any, dict[str, Any]]:
    card = verify_drop_artifact(models_dir)
    # Un pickle scikit-learn n'est garanti qu'avec la version qui l'a écrit : une autre version
    # mineure peut charger sans erreur mais prédire autrement. On refuse plutôt que de deviner.
    trained = card.get("versions", {}).get("scikit-learn")
    if trained and _minor(trained) != _minor(sklearn.__version__):
        raise ArtifactError(
            f"modèle entraîné avec scikit-learn {trained}, installé {sklearn.__version__}"
        )
    # nosec B301 : fichier produit par ce projet ET dont l'empreinte vient d'être vérifiée.
    return joblib.load(drop_paths(models_dir)[0]), card


# --- Modèle de recommandation (facteurs ALS, Parquet) ------------------------------------------


def reco_paths(models_dir: Path) -> tuple[Path, Path]:
    return models_dir / RECO_FACTORS, models_dir / RECO_CARD


def verify_reco_artifact(models_dir: Path) -> dict[str, Any]:
    return _verified_card(*reco_paths(models_dir))


def load_reco_model(models_dir: Path) -> tuple[FoldInModel, dict[str, Any]]:
    card = verify_reco_artifact(models_dir)
    if card.get("schema_version") != RECO_SCHEMA_VERSION:
        raise ArtifactError(f"schema_version {card.get('schema_version')!r} non supportée")
    df = pd.read_parquet(reco_paths(models_dir)[0])
    p = card["fold_in"]
    ids = df["anime_id"].to_numpy()
    factors = np.vstack(df["factors"].to_numpy()) if len(df) else np.empty((0, p["rank"]))
    # Le sha256 prouve que le fichier n'a pas changé, pas qu'il était correct à l'écriture.
    if factors.shape != (card["n_items"], p["rank"]):
        raise ArtifactError(f"facteurs {factors.shape}, attendu ({card['n_items']}, {p['rank']})")
    if len(np.unique(ids)) != len(ids):
        raise ArtifactError("anime_id en double dans les facteurs")
    if not np.all(np.isfinite(factors)):
        raise ArtifactError("facteurs non finis (NaN ou infini)")
    model = FoldInModel(
        item_ids=ids,
        factors=factors,
        reg_param=p["reg_param"],
        implicit=p["implicit"],
        alpha=p["alpha"],
        rating_offset=p["rating_offset"],
    )
    return model, card


def check_reco_parity(model: FoldInModel, card: dict[str, Any]) -> None:
    """Rejoue le cas de référence de la fiche : mêmes notes → exactement le même top 10.

    Garde-fou au démarrage de l'API : si le fold-in, les facteurs ou leur lecture ont changé
    depuis l'entraînement, on le voit tout de suite au lieu de servir des recos fausses.
    """
    check = card.get("parity_check") or {}
    ids, expected = check.get("anime_ids", []), check.get("expected_top10", [])
    if not ids or not expected:
        raise ArtifactError("parity_check absent ou vide dans la fiche")
    vec = fold_in(model, np.array(ids), np.array(check["scores"], dtype=float))
    got = [] if vec is None else recommend(model, vec, exclude=ids, k=len(expected)).tolist()
    if got != expected:
        raise ArtifactError(f"parity_check échoué : top attendu {expected}, obtenu {got}")
