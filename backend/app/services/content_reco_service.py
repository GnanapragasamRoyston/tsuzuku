"""Recos par le contenu (phase 10, SPEC § 6.3, ADR 013) : manga, manhwa, manhua et cross-média.

L'API n'a jamais besoin du modèle d'embeddings (ni de PyTorch) : les vecteurs sont déjà en base
(`make embeddings`). Profil = moyenne des embeddings des œuvres aimées, TOUS types confondus,
pondérée par (note − note neutre) : un anime aimé peut faire remonter un manhwa. Classement par
distance cosinus (pgvector, recherche exacte : ~21 000 lignes, aucun résultat perdu au filtrage).
"""

import json
from collections.abc import Iterable, Sequence
from typing import Any

import numpy as np
from sqlalchemy import bindparam, text
from sqlalchemy.orm import Session

from app.schemas.demo import LikedItem
from app.services import catalog_service


def _vectors(session: Session, media_ids: Iterable[int]) -> dict[int, np.ndarray]:
    ids = list(media_ids)
    if not ids:
        return {}
    rows = session.execute(
        text("SELECT media_id, embedding::text FROM catalog.media_embedding"
             " WHERE media_id IN :ids").bindparams(bindparam("ids", expanding=True)),
        {"ids": ids},
    ).all()  # fmt: skip
    # Format texte de pgvector « [0.1,0.2,…] » : du JSON valide.
    return {mid: np.asarray(json.loads(v), dtype=np.float32) for mid, v in rows}


def _prior(media: Any) -> float:
    """1 / log2(1 + rang), 0 sans rang : la même formule que NEAREST (SQL)."""
    rank = media.popularity
    return 1.0 / float(np.log2(1 + rank)) if rank and rank >= 1 else 0.0


def _as_vector(v: np.ndarray) -> str:
    return "[" + ",".join(f"{x:.7g}" for x in v.tolist()) + "]"


ALL_KINDS = ("anime", "manga", "manhwa", "manhua")
# Score = cosinus + β × a priori de popularité 1 / log2(1 + rang), 0 sans rang (NULL, ou 0 =
# « non classé » chez MAL : ln(1) = 0 ferait une division par zéro) : même formule
# que l'évaluation (pipeline embeddings/evaluate.popularity_prior), β réglé sur la validation.
NEAREST = text(
    "SELECT e.media_id FROM catalog.media_embedding e JOIN catalog.media m ON m.id = e.media_id"
    " WHERE m.kind IN :kinds AND NOT (e.media_id = ANY(CAST(:exclude AS bigint[])))"
    " ORDER BY (1 - (e.embedding <=> CAST(:profile AS vector)))"
    " + :beta * CASE WHEN m.popularity >= 1 THEN ln(2) / ln(1 + m.popularity) ELSE 0 END"
    " DESC, e.media_id LIMIT :k"
).bindparams(bindparam("kinds", expanding=True))


def _nearest(
    session: Session,
    profile: np.ndarray,
    kinds: Sequence[str],
    exclude: set[int],
    k: int,
    beta: float,
) -> list[int]:
    params = {"kinds": list(kinds), "exclude": sorted(exclude), "profile": _as_vector(profile),
              "k": k, "beta": beta}  # fmt: skip
    return [r[0] for r in session.execute(NEAREST, params).all()]


def recommend(
    session: Session,
    liked: list[LikedItem],
    kinds: Sequence[str],
    k: int,
    exclude_media_ids: Iterable[int],
    default_score: float,
    neutral_score: float,
    beta: float,
) -> dict[str, Any]:
    weights = {i.media_id: (i.score or default_score) - neutral_score for i in liked}
    weights = {mid: w for mid, w in weights.items() if w > 0}
    vectors = _vectors(session, weights)
    seen = set(exclude_media_ids) | {i.media_id for i in liked}
    # Ignorés = goûts positifs sans embedding (une mauvaise note n'est pas « ignorée »).
    ignored = sorted(set(weights) - set(vectors))

    if not vectors:
        # Aucun goût exprimé sur une œuvre qui a un embedding : popularité du type, dite telle.
        popular = catalog_service.popular(session, list(kinds), k + len(seen), 0)
        kept = [m for m in popular if m.id not in seen][:k]
        # Pas de score de modèle : le rang décroissant, comme le repli de l'ALS (reco_service).
        items = [{"media": m, "score": float(len(kept) - r), "because": None}
                 for r, m in enumerate(kept)]  # fmt: skip
        return {"strategy": "popularity", "liked_used": 0, "liked_ignored": ignored,
                "reason": "aucune œuvre aimée exploitable : recommandations populaires",
                "items": items}  # fmt: skip

    liked_ids = list(vectors)
    liked_matrix = np.vstack([vectors[m] for m in liked_ids])
    w = np.array([weights[m] for m in liked_ids])
    profile = (w[:, None] * liked_matrix).sum(axis=0)
    profile /= np.linalg.norm(profile)

    rec_ids = _nearest(session, profile, kinds, seen, k, beta)
    rec_vectors = _vectors(session, rec_ids)
    media = catalog_service.media_by_ids(session, [*rec_ids, *liked_ids])
    items = []
    for mid in rec_ids:
        v = rec_vectors[mid]
        # « Parce que tu as aimé X » : l'œuvre aimée la plus proche de la reco, de tout type.
        closest = liked_ids[int(np.argmax(liked_matrix @ v))]
        items.append({"media": media[mid], "score": float(profile @ v) + beta * _prior(media[mid]),
                      "because": media[closest].title if closest in media else None})  # fmt: skip
    return {
        "strategy": "content",
        "reason": f"profil calculé à partir de {len(liked_ids)} œuvre(s) aimée(s), "
        "tous types confondus",
        "liked_used": len(liked_ids),
        "liked_ignored": ignored,
        "items": items,
    }


def similar(session: Session, media_id: int, k: int) -> list[Any]:
    """Œuvres les plus proches (tous types), sans l'œuvre elle-même ; [] sans embedding.

    Similarité PURE (β = 0) : tous les types sont mélangés ici, et les rangs de popularité des
    animes (MAL) et des mangas (AniList) ne se comparent pas (revue de la phase 10). Les recos
    par type, elles, restent hybrides : manga, manhwa et manhua ont tous des rangs AniList."""
    own = _vectors(session, [media_id]).get(media_id)
    if own is None:
        return []
    ids = _nearest(session, own, ALL_KINDS, {media_id}, k, 0.0)
    media = catalog_service.media_by_ids(session, ids)
    return [media[i] for i in ids if i in media]
