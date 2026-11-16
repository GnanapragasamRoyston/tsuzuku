"""Features du modèle de drop — UNE définition, deux implémentations.

- `spark_drop_features` : entraînement, sur les 71 M lignes Completed/Dropped (Spark) ;
- `feature_row`        : production (API, phase 5), pour un utilisateur Tsuzuku (Python pur).
Un test de parité vérifie qu'elles donnent exactement les mêmes valeurs : c'est la protection
contre le « training-serving skew » (un modèle servi avec des features calculées autrement que
pendant l'entraînement donne des prédictions fausses sans aucune erreur visible).

Règle produit (SPEC § 6.1) : chaque feature doit être calculable depuis la liste d'un utilisateur
Tsuzuku. Les features utilisateur sont donc calculées sur SES AUTRES lignes (leave-one-out) :
la ligne qu'on cherche à prédire n'y contribue jamais.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass, field

from pyspark.sql import Column, DataFrame
from pyspark.sql import functions as F

from tsuzuku_pipeline.spark.retention_stats import StatusCodes

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


# --- Spark (entraînement) ----------------------------------------------------------------------


def _ratio(num: Column, den: Column) -> Column:
    return F.when(den > 0, num / den)


def spark_drop_features(
    animelist: DataFrame, anime: DataFrame, codes: StatusCodes, genres: Sequence[str]
) -> DataFrame:
    """Une ligne par (utilisateur, anime) Completed ou Dropped : cible + features.

    Leave-one-out sans auto-jointure : on calcule les totaux de chaque utilisateur sur TOUTE sa
    liste, puis on retire la contribution de la ligne courante. Une seule agrégation par
    utilisateur au lieu de comparer chaque ligne à toutes les autres.
    """
    g_cols, s_cols = genre_columns(genres), share_columns(genres)
    catalog = anime.select(
        "anime_id",
        F.col("type").alias("format"),
        "episodes",
        "duration_min",
        "source",
        "start_year",
        F.col("rating").alias("age_rating"),
        "popularity",
        # Studio principal = 1er listé ; null si aucun (element_at renvoie null sur liste vide).
        F.element_at("studios", 1).alias("main_studio"),
        *[
            # genres null → 0 (et non null), comme côté Python.
            F.coalesce(F.array_contains("genres", g).cast("int"), F.lit(0)).alias(c)
            for g, c in zip(genres, g_cols, strict=True)
        ],
    )

    status = F.col("watching_status")
    is_cd = status.isin(codes.completed, codes.dropped)
    is_d = (status == codes.dropped).cast("int")
    # coalesce : une note nulle compte comme « non notée » (0), comme côté Python ; sans ça, null
    # se propagerait et annulerait la note moyenne de toute la ligne (revue, parité).
    has_score = F.coalesce((F.col("score") > 0).cast("int"), F.lit(0))
    rows = animelist.select("user_id", "anime_id", "score", "watching_status").join(
        F.broadcast(catalog), "anime_id"
    )

    totals = rows.groupBy("user_id").agg(
        F.count(F.lit(1)).alias("t_all"),
        F.sum(is_cd.cast("int")).alias("t_cd"),
        F.sum(is_d).alias("t_d"),
        F.sum(F.when(F.col("score") > 0, F.col("score")).otherwise(0)).alias("t_score_sum"),
        F.sum(has_score).alias("t_score_n"),
        *[F.sum(c).alias(f"t_{c}") for c in g_cols],
    )

    # broadcast : ~320 000 utilisateurs × ~46 compteurs ≈ 100 Mo, copiés sur chaque tâche. Sans
    # ça, Spark redistribue (shuffle) les 71 M lignes larges par user_id pour la jointure : le
    # 1er run réel a saturé le disque de déversement à cette étape.
    examples = rows.where(is_cd).join(F.broadcast(totals), "user_id")
    list_size = F.col("t_all") - 1
    cd_count = F.col("t_cd") - 1
    own_score = F.when(F.col("score") > 0, F.col("score")).otherwise(0)
    shares = [
        _ratio(F.col(f"t_{g}") - F.col(g), list_size).alias(s)
        for g, s in zip(g_cols, s_cols, strict=True)
    ]

    # Affinité : moyenne des parts de l'utilisateur sur les genres de l'œuvre visée.
    n_genres = sum((F.col(g) for g in g_cols), F.lit(0))
    weighted = sum(
        (F.col(g) * _ratio(F.col(f"t_{g}") - F.col(g), list_size) for g in g_cols), F.lit(0.0)
    )
    affinity = F.when((n_genres > 0) & (list_size > 0), weighted / n_genres)

    return examples.select(
        "user_id",
        "anime_id",
        is_d.alias("is_dropped"),
        *CATEGORICAL_COLUMNS,
        *ANIME_NUMERIC_COLUMNS,
        *g_cols,
        list_size.alias("user_list_size"),
        cd_count.alias("user_cd_count"),
        _ratio(F.col("t_d") - is_d, cd_count).alias("user_drop_rate"),
        _ratio(F.col("t_score_sum") - own_score, F.col("t_score_n") - has_score).alias(
            "user_mean_score"
        ),
        affinity.alias("genre_affinity"),
        *shares,
    )


# --- Python pur (production) -------------------------------------------------------------------


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
    cd = [e for e in others if e.status in ("completed", "dropped")]
    drops = sum(1 for e in cd if e.status == "dropped")
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
