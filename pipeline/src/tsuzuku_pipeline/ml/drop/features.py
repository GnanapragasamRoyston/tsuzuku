"""Features du modèle de drop — implémentation Spark (entraînement).

Le CONTRAT des colonnes et l'implémentation Python pur (`feature_row`, utilisée par l'API) vivent
dans le paquet partagé `tsuzuku_ml.drop_features` (ADR 006) : le pipeline et l'API importent le
même code. Un test de parité (tests/test_drop_features.py) vérifie que les deux implémentations
donnent exactement les mêmes valeurs (protection contre le « training-serving skew »).
"""

from collections.abc import Sequence

from pyspark.sql import Column, DataFrame
from pyspark.sql import functions as F
from tsuzuku_ml.drop_features import (  # noqa: F401  (ré-exportés pour le pipeline et ses tests)
    ANIME_NUMERIC_COLUMNS,
    CATEGORICAL_COLUMNS,
    FORBIDDEN_COLUMNS,
    USER_COLUMNS,
    AnimeInfo,
    Entry,
    feature_columns,
    feature_row,
    genre_columns,
    genre_slug,
    share_columns,
)

from tsuzuku_pipeline.spark.retention_stats import StatusCodes

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
