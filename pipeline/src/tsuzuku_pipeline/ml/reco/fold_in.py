"""Fold-in : vecteur d'un NOUVEL utilisateur à partir de ses notes, sans réentraîner l'ALS.

Un utilisateur Tsuzuku n'est pas dans les données d'entraînement : il n'a pas de facteur. Mais
l'ALS alterne des moindres carrés régularisés ; à facteurs des animes Y fixés, le vecteur x d'un
utilisateur a une solution exacte. On refait donc, en NumPy, la dernière demi-étape de Spark pour
lui seul (même formule, mêmes conventions, vérifiées par un test de parité avec Spark) :

- explicite : x = (Σ y yᵀ + λ·n·I)⁻¹ Σ r·y          (n = nb de notes ; λ·n = « ALS-WR » de Spark)
- implicite : x = (YᵀY + Σ c₁ y yᵀ + λ·n₊·I)⁻¹ Σ_{r>0} (1 + c₁)·y
              avec c₁ = α·|r|, n₊ = nb de notes > 0 (Hu, Koren, Volinsky 2008 ; extension de Spark
              pour les notes négatives : préférence 0, mais confiance quand même).

En implicite, la note est d'abord recentrée (r = score − rating_offset) : une note sous le neutre
devient une préférence NÉGATIVE (« vu, pas aimé »), au lieu d'un signal positif.
Ce module ne dépend que de NumPy : le backend (phase 5) en garde une copie, vérifiée par le cas
de référence `parity_check` de la fiche modèle (ADR 005).
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field

import numpy as np


@dataclass(frozen=True)
class FoldInModel:
    """Facteurs des animes + hyperparamètres nécessaires au fold-in."""

    item_ids: np.ndarray  # (n_items,) identifiants MAL des animes
    factors: np.ndarray  # (n_items, rank)
    reg_param: float
    implicit: bool
    alpha: float = 1.0
    rating_offset: float = 0.0
    _index: dict[int, int] = field(init=False, repr=False, compare=False)
    _gram: np.ndarray | None = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        factors = np.asarray(self.factors, dtype=np.float64)
        object.__setattr__(self, "factors", factors)
        object.__setattr__(self, "item_ids", np.asarray(self.item_ids, dtype=np.int64))
        index = {int(i): pos for pos, i in enumerate(self.item_ids)}
        object.__setattr__(self, "_index", index)
        # YᵀY ne dépend pas de l'utilisateur : calculé une fois (implicite seulement).
        object.__setattr__(self, "_gram", factors.T @ factors if self.implicit else None)

    @property
    def rank(self) -> int:
        return self.factors.shape[1]

    def positions(self, anime_ids: Iterable[int]) -> np.ndarray:
        """Positions dans `factors` ; -1 pour un anime absent du modèle."""
        return np.array([self._index.get(int(a), -1) for a in anime_ids], dtype=np.int64)


def fold_in(model: FoldInModel, anime_ids: np.ndarray, scores: np.ndarray) -> np.ndarray | None:
    """Vecteur utilisateur, ou None si aucune note n'apporte d'information exploitable.

    Les animes absents du modèle (trop peu notés, ou sortis après 2020) sont ignorés : ils n'ont
    pas de facteur. None → l'appelant se rabat sur la popularité.
    """
    anime_ids, scores = np.asarray(anime_ids), np.asarray(scores, dtype=np.float64)
    if len(anime_ids) != len(scores):
        raise ValueError(f"longueur différente : {len(anime_ids)} animes, {len(scores)} notes")
    if not np.all(np.isfinite(scores)):
        raise ValueError("note manquante ou non finie (NaN) : le vecteur serait NaN")
    if len(np.unique(anime_ids)) != len(anime_ids):
        # Un anime en double compterait deux fois dans les moindres carrés.
        raise ValueError("anime en double dans les notes : une seule note par anime")
    pos = model.positions(anime_ids)
    known = pos >= 0
    y, r = model.factors[pos[known]], scores[known] - model.rating_offset
    if len(r) == 0:
        return None

    if model.implicit:
        positive = r > 0
        if not positive.any():
            return None  # aucune préférence positive : la solution serait le vecteur nul
        c1 = model.alpha * np.abs(r)
        a = model._gram + (y.T * c1) @ y
        b = ((1.0 + c1[positive])[:, None] * y[positive]).sum(axis=0)
        n = int(positive.sum())
    else:
        a = y.T @ y
        b = y.T @ r
        n = len(r)
    a = a + model.reg_param * n * np.eye(model.rank)
    # Matrice symétrique définie positive (λ > 0) : solve est exact et stable à ce rang.
    return np.linalg.solve(a, b)


def onboarding_ratings(
    choices: Iterable[int], scores: Mapping[int, int], default_score: float
) -> tuple[np.ndarray, np.ndarray]:
    """Notes d'un utilisateur à l'onboarding : un choix sans note vaut `default_score`.

    Une note explicite l'emporte toujours sur la note par défaut.
    """
    if not 1 <= default_score <= 10:
        raise ValueError(f"note par défaut : {default_score} (attendu entre 1 et 10)")
    for anime_id, score in scores.items():
        if not 1 <= score <= 10:
            raise ValueError(f"note de {anime_id} : {score} (attendu entre 1 et 10)")
    merged = {int(a): float(default_score) for a in choices}
    merged.update({int(a): float(s) for a, s in scores.items()})
    ids = list(merged)
    return np.array(ids, dtype=np.int64), np.array([merged[a] for a in ids], dtype=np.float64)


def scores_for(model: FoldInModel, user_vec: np.ndarray) -> np.ndarray:
    """Score de chaque anime du modèle pour cet utilisateur (produit scalaire)."""
    return model.factors @ user_vec


def top_k_positions(scores: np.ndarray, exclude_pos: np.ndarray, k: int) -> np.ndarray:
    """Positions des k meilleurs scores, hors `exclude_pos`. SEULE règle de classement du projet :
    l'évaluation et le service l'utilisent tous les deux (même départage des ex æquo).

    Tri stable sur -score : à score égal, l'ordre du catalogue départage (déterministe).
    """
    scores = np.array(scores, dtype=np.float64)  # copie : on masque sans toucher l'original
    exclude_pos = np.asarray(exclude_pos, dtype=np.int64)
    scores[exclude_pos[exclude_pos >= 0]] = -np.inf
    k = min(k, int(np.isfinite(scores).sum()))
    return np.argsort(-scores, kind="stable")[:k]


def recommend(
    model: FoldInModel, user_vec: np.ndarray, exclude: Iterable[int], k: int
) -> np.ndarray:
    """Les k animes de plus haut score, hors ceux déjà vus (`exclude`)."""
    top = top_k_positions(scores_for(model, user_vec), model.positions(exclude), k)
    return model.item_ids[top]


def predict_scores(model: FoldInModel, user_vec: np.ndarray, targets: np.ndarray) -> np.ndarray:
    """Notes prédites (ALS explicite) pour des animes DU CATALOGUE, bornées à l'échelle 1-10.

    Un anime inconnu lève une erreur : en NumPy, la position -1 indexerait silencieusement le
    dernier anime du catalogue.
    """
    pos = model.positions(targets)
    if (pos < 0).any():
        raise ValueError(f"animes hors catalogue : {np.asarray(targets)[pos < 0].tolist()}")
    return np.clip(model.factors[pos] @ user_vec, 1.0, 10.0)
