"""Recommandations par fold-in (ALS implicite, phase 4) avec repli sur la popularité.

Règle validée (ADR 006) : sous `min_liked_for_als` animes aimés connus du modèle, on sert la
popularité — mesuré en phase 4, l'ALS fait moins bien qu'elle avec 3 titres.
"""

from dataclasses import dataclass
from typing import Any

import numpy as np
from sqlalchemy.orm import Session
from tsuzuku_ml.fold_in import FoldInModel, fold_in, onboarding_ratings, recommend

from app.schemas.demo import LikedItem
from app.services import catalog_service


@dataclass(frozen=True)
class RecoEngine:
    model: FoldInModel
    card: dict[str, Any]
    min_liked_for_als: int

    def __post_init__(self) -> None:
        # Validées au chargement : une fiche incomplète rend le modèle indisponible au démarrage
        # (503 + /health), au lieu d'un 500 à chaque requête.
        missing = [k for k in REQUIRED_CARD_KEYS if k not in self.card]
        if missing:
            raise ValueError(f"fiche du modèle de reco incomplète : {', '.join(missing)}")

    @property
    def default_score(self) -> float:
        return float(self.card["onboarding_default_score"])

    @property
    def liked_min_score(self) -> float:
        # « Aimé » = même seuil que la pertinence mesurée en phase 4 (note ≥ 8).
        return float(self.card["relevant_min_score"])

    @property
    def popularity(self) -> list[int]:
        return [int(a) for a in self.card["popularity_fallback"]]


REQUIRED_CARD_KEYS = (
    "onboarding_default_score",
    "relevant_min_score",
    "popularity_fallback",
)
# Marge de candidats : quelques recos peuvent ne pas avoir de fiche au catalogue.
CANDIDATE_MARGIN = 20


def _because(model: FoldInModel, rec_ids: np.ndarray, liked_ids: list[int]) -> list[int | None]:
    """Pour chaque reco, l'anime AIMÉ le plus proche (cosinus des facteurs)."""
    pos = model.positions(liked_ids)
    keep = pos >= 0
    if not keep.any():
        return [None] * len(rec_ids)
    liked_arr = np.asarray(liked_ids)[keep]
    liked_f = model.factors[pos[keep]]
    liked_f = liked_f / np.maximum(np.linalg.norm(liked_f, axis=1, keepdims=True), 1e-12)
    out = []
    for rec in model.positions(rec_ids):
        f = model.factors[rec]
        sims = liked_f @ (f / max(np.linalg.norm(f), 1e-12))
        out.append(int(liked_arr[int(np.argmax(sims))]))
    return out


def recommend_for(
    engine: RecoEngine, session: Session, liked: list[LikedItem], k: int
) -> dict[str, Any]:
    media = catalog_service.media_by_ids(session, [item.media_id for item in liked])
    mal_of = {mid: m.mal_id for mid, m in media.items() if m.kind == "anime" and m.mal_id}
    choices = [mal_of[i.media_id] for i in liked if i.media_id in mal_of and i.score is None]
    scores = {mal_of[i.media_id]: i.score for i in liked if i.media_id in mal_of and i.score}
    ids, values = onboarding_ratings(choices, scores, engine.default_score)

    known = engine.model.positions(ids) >= 0
    unknown_mals = set(ids[~known].tolist())
    ignored = sorted(
        {i.media_id for i in liked if i.media_id not in mal_of}
        | {mid for mid, mal in mal_of.items() if mal in unknown_mals}
    )
    seen = set(ids.tolist())
    # La règle des 5 ne compte que les titres AIMÉS (note ≥ seuil) : c'est ce qui a été mesuré
    # en phase 4. Des titres mal notés sont transmis au fold-in (préférence négative) mais ne
    # rendent pas le profil plus fiable.
    is_liked = known & (values >= engine.liked_min_score)
    n_liked = int(is_liked.sum())

    vec = fold_in(engine.model, ids, values) if n_liked >= engine.min_liked_for_als else None
    if vec is None:
        strategy = "popularity"
        reason = (
            f"{n_liked} anime(s) aimé(s) reconnu(s) : il en faut au moins "
            f"{engine.min_liked_for_als} pour des recommandations personnalisées"
            if n_liked < engine.min_liked_for_als
            else "aucune préférence positive exploitable : recommandations populaires"
        )
        candidates = np.array([a for a in engine.popularity if a not in seen], dtype=np.int64)
        rec_scores: list[float | None] = [None] * len(candidates)
        because: list[int | None] = [None] * len(candidates)
    else:
        strategy, reason = "als", f"profil calculé à partir de {n_liked} anime(s) aimé(s)"
        candidates = recommend(engine.model, vec, exclude=list(seen), k=k + CANDIDATE_MARGIN)
        rec_scores = (engine.model.factors[engine.model.positions(candidates)] @ vec).tolist()
        because = _because(engine.model, candidates, ids[is_liked].tolist())

    by_mal = catalog_service.anime_by_mal(session, [*candidates.tolist(), *ids.tolist()])
    items = []
    for mal, score, why in zip(candidates.tolist(), rec_scores, because, strict=True):
        if mal not in by_mal:
            continue  # facteur sans fiche au catalogue : rien à afficher, on prend le suivant
        items.append({"media": by_mal[mal], "score": score,
                      "because": by_mal[why].title if why in by_mal else None})  # fmt: skip
        if len(items) == k:
            break
    if strategy == "popularity":
        # Pas de score de modèle : un score décroissant (le rang) garde un ordre lisible.
        for rank, item in enumerate(items):
            item["score"] = float(len(items) - rank)
    return {
        "strategy": strategy,
        "reason": reason,
        "liked_used": n_liked if strategy == "als" else 0,
        "liked_ignored": ignored,
        "items": items,
    }
