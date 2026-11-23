"""Modèles servis lus depuis Cloud Storage (production, phase 11, ADR 014).

En local, les artefacts sont dans models/ (make train, make reco). Sur Cloud Run, le système de
fichiers est éphémère : avec MODELS_URI=gs://bucket/préfixe, l'API copie au démarrage les QUATRE
fichiers servis (jamais l'historique runs/) dans MODELS_DIR, puis les charge comme d'habitude :
le sha256 de chaque fiche est vérifié au chargement, rien n'est cru sur parole.
Authentification : le compte de service de Cloud Run (lecture seule sur ce bucket), sans clé.
"""

import os
import tempfile
from pathlib import Path
from typing import Any

from tsuzuku_ml.artifacts import DROP_NAME, RECO_CARD, RECO_FACTORS

MODEL_FILES = (f"{DROP_NAME}.joblib", f"{DROP_NAME}.json", RECO_FACTORS, RECO_CARD)


def _parse(uri: str) -> tuple[str, str]:
    if not uri.startswith("gs://"):
        raise ValueError(f"MODELS_URI doit commencer par gs:// : {uri!r}")
    bucket, _, prefix = uri.removeprefix("gs://").partition("/")
    if not bucket:
        raise ValueError(f"MODELS_URI sans nom de bucket : {uri!r}")
    return bucket, prefix.strip("/")


def download_models(uri: str, dest: Path, client: Any = None) -> list[Path]:
    bucket_name, prefix = _parse(uri)
    if client is None:
        from google.cloud import storage  # seulement en production (MODELS_URI défini)

        client = storage.Client()
    bucket = client.bucket(bucket_name)
    dest.mkdir(parents=True, exist_ok=True)
    # Tout ou rien : téléchargement dans un dossier temporaire, puis remplacement des 4 fichiers
    # seulement s'ils sont tous arrivés. Un échec laisse les modèles en place intacts (jamais un
    # modèle neuf avec l'ancienne fiche).
    with tempfile.TemporaryDirectory(dir=dest) as tmp:
        for name in MODEL_FILES:
            bucket.blob(f"{prefix}/{name}" if prefix else name).download_to_filename(
                str(Path(tmp) / name)
            )
        for name in MODEL_FILES:
            os.replace(Path(tmp) / name, dest / name)
    return [dest / name for name in MODEL_FILES]
