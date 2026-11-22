"""Scorer « contenu » (et hybride contenu + popularité) pour le protocole de la phase 4.

Profil d'un utilisateur = moyenne de ses œuvres aimées, pondérée par (note − note neutre) :
seules les notes au-dessus du neutre comptent comme un goût (même règle que l'ALS implicite).
Score d'une œuvre = cosinus avec le profil (vecteurs normalisés → produit scalaire)
+ β × a priori de popularité.

Pourquoi l'hybride (mesuré, ADR 013) : le contenu seul recommande des œuvres proches mais
obscures et fait bien moins bien que la popularité sur les animes du dataset. L'a priori de
popularité remonte, parmi les œuvres proches, celles que les gens connaissent ; β est réglé sur
les utilisateurs de validation, le test n'est mesuré qu'une fois.
"""

import numpy as np
import pandas as pd

from tsuzuku_pipeline.ml.reco.evaluate import Scorer


def popularity_prior(ranks: np.ndarray) -> np.ndarray:
    """1 / log2(1 + rang) : 1 pour le n° 1, décroît lentement (rang 10 ≈ 0,29, 5 000 ≈ 0,08) ;
    0 sans rang. Même formule que le service (content_reco_service), en SQL."""
    r = np.asarray(ranks, dtype=float)
    out = np.zeros(len(r))
    ok = np.isfinite(r) & (r >= 1)
    out[ok] = 1.0 / np.log2(1.0 + r[ok])
    return out


def content_scorer(
    item_ids: np.ndarray,
    embeddings: np.ndarray,
    neutral_score: float,
    prior: np.ndarray | None = None,
    beta: float = 0.0,
) -> Scorer:
    index = pd.Index(item_ids)
    boost = beta * prior if prior is not None and beta else 0.0

    def score(ids: np.ndarray, scores: np.ndarray) -> np.ndarray | None:
        pos = index.get_indexer(ids)
        weights = np.asarray(scores, dtype=float) - neutral_score
        keep = (pos >= 0) & (weights > 0)
        if not keep.any():
            return None  # aucun goût exprimé sur une œuvre connue : repli (popularité)
        profile = (weights[keep, None] * embeddings[pos[keep]]).sum(axis=0)
        norm = np.linalg.norm(profile)
        return None if norm == 0 else embeddings @ (profile / norm) + boost

    return score


def knee_beta(val_ndcg: dict[float, float], tolerance: float) -> float:
    """Plus petit β dont le NDCG de validation est à moins de `tolerance` (relatif) du meilleur.

    Au-delà du coude, augmenter β ne gagne presque plus rien en NDCG mais transforme les recos
    en top populaire (couverture du catalogue qui s'effondre) : on garde le moins de popularité
    possible pour un score quasi identique (choix de Royston, 2026-11-22, ADR 013)."""
    best = max(val_ndcg.values())
    return min(b for b, v in val_ndcg.items() if v >= (1 - tolerance) * best)
