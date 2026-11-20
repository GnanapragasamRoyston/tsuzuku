"""Risque de drop d'une œuvre pour un utilisateur, à partir de sa liste (modèle de la phase 3).

Les features sont calculées par le MÊME code qu'à l'entraînement (tsuzuku_ml.drop_features :
feature_row puis prepare_x) : pas de « training-serving skew ».
Mangas et manhwas : pas de modèle tant que les données manquent (SPEC § 6.4) — on le dit au lieu
d'afficher un chiffre inventé.
"""

from dataclasses import dataclass
from typing import Any

import pandas as pd
from sqlalchemy.orm import Session
from tsuzuku_ml.drop_features import (
    COMPLETED,
    DROPPED,
    OTHER,
    Entry,
    feature_columns,
    feature_row,
    prepare_x,
)

from app.db.models import CriticalEpisode, Media
from app.schemas.demo import ListEntryIn
from app.services import catalog_service

# Statuts Tsuzuku → statuts vus par le modèle (Completed / Dropped / le reste de la liste).
STATUS_MAP = {"completed": COMPLETED, "dropped": DROPPED}


@dataclass(frozen=True)
class DropEngine:
    model: Any  # pipeline scikit-learn chargé et vérifié par tsuzuku_ml.artifacts
    card: dict[str, Any]

    def __post_init__(self) -> None:
        # Validé au chargement (et non à la 1re requête) : fiche incomplète ou pickle qui ne
        # correspond pas à la fiche → modèle indisponible dès le démarrage.
        missing = [k for k in ("genres", "threshold") if k not in self.card]
        if missing:
            raise ValueError(f"fiche du modèle de drop incomplète : {', '.join(missing)}")
        expected = feature_columns(self.card["genres"])
        names = getattr(self.model, "feature_names_in_", None)
        if names is not None and list(names) != expected:
            raise ValueError("colonnes du modèle de drop différentes du contrat de la fiche")

    @property
    def genres(self) -> list[str]:
        return list(self.card["genres"])

    @property
    def threshold(self) -> float:
        return float(self.card["threshold"])


class MediaNotFound(Exception):
    pass


def drop_risk(
    engine: DropEngine, session: Session, media_id: int, entries: list[ListEntryIn]
) -> dict[str, Any]:
    target = session.get(Media, media_id)
    if target is None:
        raise MediaNotFound(media_id)
    critical = session.get(CriticalEpisode, media_id)
    base = {
        "media_id": media_id,
        "critical_episode": critical.critical_episode if critical else None,
        "point_of_no_return": critical.point_of_no_return if critical else None,
    }
    if target.kind != "anime" or target.mal_id is None:
        return {**base, "status": "insufficient_data",
                "message": "Pas encore assez de données pour estimer le risque de drop de ce "
                           "type d'œuvre (modèle entraîné sur des animes)."}  # fmt: skip

    listed = catalog_service.media_by_ids(session, [e.media_id for e in entries])
    infos = catalog_service.anime_infos(session, [target, *listed.values()])
    if target.mal_id not in infos:
        # Anime ajouté après le dataset (Jikan, AniList) : le modèle n'a jamais vu ses features.
        # Un chiffre serait calculé sur des valeurs vides : on ne l'affiche pas.
        return {**base, "status": "insufficient_data",
                "message": "Œuvre plus récente que les données d'entraînement (2020) : pas "
                           "encore assez de données pour estimer son risque de drop."}  # fmt: skip
    ml_entries = [
        Entry(listed[e.media_id].mal_id, STATUS_MAP.get(e.status, OTHER), e.score)
        for e in entries
        if e.media_id in listed and listed[e.media_id].mal_id in infos
    ]
    row = feature_row(ml_entries, target.mal_id, infos, engine.genres)
    x = prepare_x(pd.DataFrame([row]), engine.genres)
    probability = float(engine.model.predict_proba(x)[0, 1])
    return {
        **base,
        "status": "ok",
        "probability": probability,
        "threshold": engine.threshold,
        "at_risk": probability >= engine.threshold,
        # La cible elle-même est exclue de ses features (leave-one-out).
        "entries_used": sum(1 for e in ml_entries if e.anime_id != target.mal_id),
    }
