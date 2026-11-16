"""Entraînement ALS (Spark MLlib) et baseline de popularité.

Deux variantes d'ALS sont comparées :
- explicite : prédit la note (1-10) ; c'est la seule dont la RMSE a un sens ;
- implicite : la note sert de CONFIANCE (Hu et al. 2008), recentrée sur un score neutre ; le
  modèle apprend « ce que l'utilisateur va regarder et aimer », souvent meilleur en classement.
Le choix entre les deux se fait sur la NDCG@K de validation (on recommande une liste, on ne
prédit pas une note).
"""

import logging
import time
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd
from pyspark.ml.recommendation import ALS
from pyspark.sql import DataFrame
from pyspark.sql import functions as F

from tsuzuku_pipeline.ml.reco.fold_in import FoldInModel, fold_in, predict_scores, scores_for

logger = logging.getLogger("tsuzuku_pipeline.reco")

KINDS = ("als_explicit", "als_implicit")


@dataclass(frozen=True)
class GridPoint:
    kind: str
    rank: int
    reg_param: float

    @property
    def implicit(self) -> bool:
        return self.kind == "als_implicit"


def grid_points(cfg: dict[str, Any]) -> Iterator[GridPoint]:
    for kind in KINDS:
        for rank in cfg["ranks"]:
            for reg in cfg["reg_params"]:
                yield GridPoint(kind, int(rank), float(reg))


def rating_offset(point: GridPoint, cfg: dict[str, Any]) -> float:
    # Implicite : note − neutre. Une note ≤ neutre n'est pas une préférence positive (« vu, pas
    # aimé ») mais garde une confiance α·|écart|. Explicite : la note brute.
    return float(cfg["implicit_neutral_score"]) if point.implicit else 0.0


def fit_als(ratings: DataFrame, point: GridPoint, cfg: dict[str, Any], seed: int) -> FoldInModel:
    """Entraîne un ALS Spark et renvoie ses facteurs d'animes, prêts pour le fold-in."""
    offset = rating_offset(point, cfg)
    data = ratings.select(
        "user_id", "anime_id", (F.col("score") - F.lit(offset)).cast("float").alias("rating")
    )
    als = ALS(
        rank=point.rank,
        maxIter=cfg["max_iter"],
        regParam=point.reg_param,
        implicitPrefs=point.implicit,
        alpha=float(cfg["implicit_alpha"]),
        userCol="user_id",
        itemCol="anime_id",
        ratingCol="rating",
        numUserBlocks=cfg["num_blocks"],
        numItemBlocks=cfg["num_blocks"],
        seed=seed,
    )
    started = time.monotonic()
    fitted = als.fit(data)
    items = fitted.itemFactors.toPandas().sort_values("id")
    logger.info("ALS %s : %.0f s", point, time.monotonic() - started)
    return FoldInModel(
        item_ids=items["id"].to_numpy(),
        factors=np.vstack(items["features"].to_numpy()),
        reg_param=point.reg_param,
        implicit=point.implicit,
        alpha=float(cfg["implicit_alpha"]),
        rating_offset=offset,
    )


def als_scorer(model: FoldInModel):
    def score(ids: np.ndarray, scores: np.ndarray) -> np.ndarray | None:
        vec = fold_in(model, ids, scores)
        return None if vec is None else scores_for(model, vec)

    return score


def als_predictor(model: FoldInModel, item_means: pd.Series):
    """Note prédite par l'ALS explicite (bornée à 1-10) ; sans vecteur utilisateur, la moyenne
    de l'anime."""

    def predict(ids: np.ndarray, scores: np.ndarray, targets: np.ndarray) -> np.ndarray:
        vec = fold_in(model, ids, scores)
        if vec is None:
            return item_means.reindex(targets).to_numpy(dtype=float)
        return predict_scores(model, vec, targets)

    return predict


def item_stats(train: DataFrame, relevant_min_score: float) -> pd.DataFrame:
    """Par anime : somme et nombre de notes (baseline RMSE), nombre de notes pertinentes
    (baseline de popularité). Agrégé par Spark : quelques milliers de lignes en sortie."""
    return (
        train.groupBy("anime_id")
        .agg(
            F.sum("score").cast("double").alias("sum"),
            F.count("*").alias("count"),
            F.sum((F.col("score") >= relevant_min_score).cast("int")).alias("relevant"),
        )
        .toPandas()
    )


def popularity_scores(stats: pd.DataFrame, item_ids: np.ndarray) -> np.ndarray:
    """Score de popularité aligné sur le catalogue : nb de notes pertinentes dans le train."""
    return stats.set_index("anime_id")["relevant"].reindex(item_ids).fillna(0).to_numpy(float)
