"""Export du modèle de recommandation : facteurs des animes (Parquet) + fiche modèle (JSON).

Le backend n'a besoin que des facteurs des animes et des hyperparamètres du fold-in : pas de
JVM, pas de pickle. Même organisation que le modèle de drop :
- models/runs/<run_id>/reco_item_factors.parquet + reco_model.json : copie par run, jamais
  écrasée ;
- models/reco_item_factors.parquet + reco_model.json : le modèle « courant » (copie atomique).
Le sha256 du Parquet est dans la fiche : facteurs et fiche ne peuvent pas être mélangés entre deux
runs sans que la vérification échoue.
"""

import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from tsuzuku_pipeline.ml.drop.export import ArtifactError, _atomic_copy, _sha256
from tsuzuku_pipeline.ml.reco.fold_in import FoldInModel

FACTORS_NAME, CARD_NAME = "reco_item_factors.parquet", "reco_model.json"
SCHEMA_VERSION = 1


def reco_paths(models_dir: Path) -> tuple[Path, Path]:
    return models_dir / FACTORS_NAME, models_dir / CARD_NAME


def save_reco_artifact(
    model: FoldInModel, card: dict[str, Any], models_dir: Path
) -> dict[str, Any]:
    """Écrit la copie du run puis remplace le modèle courant. Renvoie la fiche complétée."""
    run_dir = models_dir / "runs" / card["run_id"]
    run_dir.mkdir(parents=True, exist_ok=True)
    run_factors, run_card = reco_paths(run_dir)
    pd.DataFrame(
        {"anime_id": model.item_ids, "factors": list(model.factors.astype(np.float32))}
    ).to_parquet(run_factors, index=False)

    card = {
        **card,
        # Contrat lu par le backend (phase 5) : à incrémenter si le format change.
        "schema_version": SCHEMA_VERSION,
        "n_items": int(len(model.item_ids)),
        "score_scale": [1, 10],
        "fold_in": {
            "rank": model.rank,
            "reg_param": model.reg_param,
            "implicit": model.implicit,
            "alpha": model.alpha,
            "rating_offset": model.rating_offset,
        },
        "artifact": run_factors.relative_to(models_dir.parent).as_posix(),
        "artifact_sha256": _sha256(run_factors),
    }
    run_card.write_text(json.dumps(card, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    current_factors, current_card = reco_paths(models_dir)
    # Facteurs d'abord, fiche en dernier (voir ml/drop/export.py).
    _atomic_copy(run_factors, current_factors)
    _atomic_copy(run_card, current_card)
    return card


def verify_reco_artifact(models_dir: Path) -> dict[str, Any]:
    factors, card_path = reco_paths(models_dir)
    if not factors.is_file() or not card_path.is_file():
        raise ArtifactError(f"Modèle de reco incomplet dans {models_dir}")
    card = json.loads(card_path.read_text(encoding="utf-8"))
    expected = card.get("artifact_sha256")
    if not expected or _sha256(factors) != expected:
        raise ArtifactError(f"{factors.name} : sha256 absent de la fiche ou différent")
    return card


def load_reco_model(models_dir: Path) -> tuple[FoldInModel, dict[str, Any]]:
    card = verify_reco_artifact(models_dir)
    if card.get("schema_version") != SCHEMA_VERSION:
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
