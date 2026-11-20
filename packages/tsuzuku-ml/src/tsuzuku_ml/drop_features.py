"""Features du modèle de drop : le CONTRAT des colonnes et le calcul en Python pur (production).

Une définition, deux implémentations :
- `tsuzuku_pipeline.ml.drop.features.spark_drop_features` : entraînement, sur les 71 M lignes ;
- `feature_row` (ici) : API, pour un utilisateur Tsuzuku.
Un test de parité (côté pipeline, il a besoin de Spark) vérifie qu'elles donnent exactement les
mêmes valeurs : c'est la protection contre le « training-serving skew » (un modèle servi avec des
features calculées autrement qu'à l'entraînement donne des prédictions fausses sans erreur).

Ce module vit dans le paquet partagé tsuzuku_ml : le pipeline et l'API importent LE MÊME code
(ADR 006), il n'y a pas de copie qui pourrait diverger.

Règle produit (SPEC § 6.1) : chaque feature doit être calculable depuis la liste d'un utilisateur
Tsuzuku. Les features utilisateur sont donc calculées sur SES AUTRES lignes (leave-one-out) :
la ligne qu'on cherche à prédire n'y contribue jamais.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

# Fuite de la cible (ADR 004) : ces colonnes décrivent l'issue ou en sont un agrégat.
# - watched_episodes : un drop a mécaniquement moins d'épisodes vus ;
# - score : 54 % des drops ne sont pas notés contre 15 % des Completed (mesuré sur clean) ;
# - agrégats MAL (dropped, completed, ..., mal_score, score_1..10) : comptent la ligne elle-même.
FORBIDDEN_COLUMNS = frozenset(
    {
        "watched_episodes",
        "score",
        "watching_status",
        "is_dropped",
        "dropped",
        "completed",
        "watching",
        "on_hold",
        "plan_to_watch",
        "members",
        "favorites",
        "mal_score",
        "ranked",
        *(f"score_{i}" for i in range(1, 11)),
    }
)

CATEGORICAL_COLUMNS = ("format", "source", "age_rating", "main_studio")
ANIME_NUMERIC_COLUMNS = ("episodes", "duration_min", "start_year", "popularity")
USER_COLUMNS = (
    "user_list_size",
    "user_cd_count",
    "user_drop_rate",
    "user_mean_score",
    "genre_affinity",
)
# Statuts reconnus par feature_row. Tout autre statut d'une liste compte dans la taille de la
# liste mais pas dans les Completed/Dropped (comme Watching / On Hold / Plan to Watch côté Spark).
COMPLETED, DROPPED, OTHER = "completed", "dropped", "other"


def genre_slug(genre: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", genre.lower()).strip("_")


def genre_columns(genres: Sequence[str]) -> list[str]:
    return [f"genre_{genre_slug(g)}" for g in genres]


def share_columns(genres: Sequence[str]) -> list[str]:
    return [f"user_share_{genre_slug(g)}" for g in genres]


def feature_columns(genres: Sequence[str]) -> list[str]:
    """Colonnes d'entrée du modèle, dans un ordre stable (contrat avec l'API)."""
    return [
        *CATEGORICAL_COLUMNS,
        *ANIME_NUMERIC_COLUMNS,
        *genre_columns(genres),
        *USER_COLUMNS,
        *share_columns(genres),
    ]


@dataclass(frozen=True)
class AnimeInfo:
    genres: Sequence[str] = ()
    format: str | None = None
    episodes: int | None = None
    duration_min: float | None = None
    source: str | None = None
    start_year: int | None = None
    age_rating: str | None = None
    popularity: int | None = None
    studios: Sequence[str] = field(default_factory=tuple)


@dataclass(frozen=True)
class Entry:
    """Une ligne de liste utilisateur. status : 'completed', 'dropped' ou 'other'."""

    anime_id: int
    status: str
    score: int | None = None


def prepare_x(df: pd.DataFrame, genres: Sequence[str]) -> pd.DataFrame:
    """Matrice d'entrée : UNIQUEMENT les colonnes du contrat, types stables.

    Utilisée à l'entraînement ET par l'API : c'est ici, et nulle part ailleurs, que les données
    deviennent l'entrée du modèle. Une colonne en trop dans `df` (ex. score) est ignorée.
    """
    cols = feature_columns(genres)
    x = df[cols].copy()
    for c in cols:
        if c in CATEGORICAL_COLUMNS:
            # object + NaN : forme que SimpleImputer et OneHotEncoder gèrent sans surprise.
            x[c] = x[c].astype(object).where(x[c].notna(), np.nan)
        else:
            # float32 : divise la mémoire par deux (2 M lignes × ~100 colonnes) ; NaN conservés.
            x[c] = pd.to_numeric(x[c], errors="coerce").astype(np.float32)
    return x


def feature_row(
    entries: Sequence[Entry],
    target_anime_id: int,
    catalog: dict[int, AnimeInfo],
    genres: Sequence[str],
) -> dict:
    """Features d'un utilisateur pour une œuvre, avec exactement la sémantique Spark.

    L'œuvre visée est exclue de la liste si elle y figure (leave-one-out). Une œuvre de la liste
    absente du catalogue (ex. sortie après 2020, ou exclue car adulte) est IGNORÉE entièrement :
    c'est ce que fait la jointure interne côté Spark, donc ce que le modèle a vu à l'entraînement.
    """
    target = catalog.get(target_anime_id, AnimeInfo())
    others = [e for e in entries if e.anime_id != target_anime_id and e.anime_id in catalog]
    g_cols, s_cols = genre_columns(genres), share_columns(genres)

    list_size = len(others)
    cd = [e for e in others if e.status in (COMPLETED, DROPPED)]
    drops = sum(1 for e in cd if e.status == DROPPED)
    scores = [e.score for e in others if e.score and e.score > 0]
    counts = dict.fromkeys(genres, 0)
    for e in others:
        for g in catalog.get(e.anime_id, AnimeInfo()).genres:
            if g in counts:
                counts[g] += 1
    shares = {g: (counts[g] / list_size if list_size > 0 else None) for g in genres}

    target_genres = [g for g in genres if g in target.genres]
    if target_genres and list_size > 0:
        # Même ordre d'opérations que Spark (somme puis division) pour une parité exacte.
        affinity = sum(shares[g] for g in target_genres) / len(target_genres)
    else:
        affinity = None

    row = {
        "format": target.format,
        "source": target.source,
        "age_rating": target.age_rating,
        "main_studio": target.studios[0] if target.studios else None,
        "episodes": target.episodes,
        "duration_min": target.duration_min,
        "start_year": target.start_year,
        "popularity": target.popularity,
        **{c: int(g in target.genres) for g, c in zip(genres, g_cols, strict=True)},
        "user_list_size": list_size,
        "user_cd_count": len(cd),
        "user_drop_rate": drops / len(cd) if cd else None,
        "user_mean_score": sum(scores) / len(scores) if scores else None,
        "genre_affinity": affinity,
        **{s: shares[g] for g, s in zip(genres, s_cols, strict=True)},
    }
    return {c: row[c] for c in feature_columns(genres)}
