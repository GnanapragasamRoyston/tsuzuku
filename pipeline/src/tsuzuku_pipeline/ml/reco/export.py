"""Export du modèle de recommandation : facteurs des animes (Parquet) + fiche modèle (JSON).

L'API n'a besoin que des facteurs des animes et des hyperparamètres du fold-in : pas de JVM, pas
de pickle. Vérification et chargement vivent dans le paquet partagé (tsuzuku_ml.artifacts), pour
que le pipeline et l'API appliquent les mêmes contrôles.
- models/runs/<run_id>/reco_item_factors.parquet + reco_model.json : copie par run ;
- models/reco_item_factors.parquet + reco_model.json : le modèle « courant » (copie atomique).
"""

import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from tsuzuku_ml.artifacts import (  # noqa: F401  (ré-exportés pour le pipeline et ses tests)
    RECO_SCHEMA_VERSION,
    ArtifactError,
    atomic_copy,
    load_reco_model,
    reco_paths,
    sha256_file,
    verify_reco_artifact,
)
from tsuzuku_ml.fold_in import FoldInModel


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
        "schema_version": RECO_SCHEMA_VERSION,
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
        "artifact_sha256": sha256_file(run_factors),
    }
    run_card.write_text(json.dumps(card, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    current_factors, current_card = reco_paths(models_dir)
    # Facteurs d'abord, fiche en dernier : si on s'arrête entre les deux, l'empreinte de
    # l'ancienne fiche ne correspond plus et le chargement est refusé (pas de mélange).
    atomic_copy(run_factors, current_factors)
    atomic_copy(run_card, current_card)
    return card
