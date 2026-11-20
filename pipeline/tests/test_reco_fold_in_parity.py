"""Fold-in : le vecteur d'un utilisateur calculé en NumPy doit être celui que Spark aurait calculé.

Test de parité : Spark ALS met à jour les utilisateurs EN DERNIER à chaque itération, donc ses
facteurs utilisateur sont exactement la solution des moindres carrés régularisés étant donnés les
facteurs des animes finaux. Notre fold-in (paquet partagé tsuzuku_ml, utilisé tel quel par l'API),
appliqué aux mêmes notes, doit retrouver ces vecteurs. Ce test vit côté pipeline : il a besoin de
Spark, que le paquet partagé n'embarque pas.
"""

import numpy as np
import pandas as pd
import pytest
from pyspark.ml.recommendation import ALS
from tsuzuku_ml.fold_in import FoldInModel, fold_in


def _ratings(seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    rows = [
        (u, i, int(rng.integers(1, 11)))
        for u in range(1, 31)
        for i in range(100, 116)
        if rng.random() < 0.6
    ]
    return pd.DataFrame(rows, columns=["user_id", "anime_id", "score"])


def _spark_model(spark, ratings: pd.DataFrame, implicit: bool, offset: float = 0.0):
    df = ratings.assign(score=ratings["score"].astype(float) - offset)
    als = ALS(
        rank=4,
        regParam=0.1,
        maxIter=15,
        implicitPrefs=implicit,
        alpha=0.5,
        userCol="user_id",
        itemCol="anime_id",
        ratingCol="score",
        seed=42,
    )
    fitted = als.fit(spark.createDataFrame(df))
    items = fitted.itemFactors.toPandas().sort_values("id")
    users = fitted.userFactors.toPandas().set_index("id")
    model = FoldInModel(
        item_ids=items["id"].to_numpy(),
        factors=np.vstack(items["features"].to_numpy()),
        reg_param=0.1,
        implicit=implicit,
        alpha=0.5,
        rating_offset=offset,
    )
    return model, users


@pytest.mark.parametrize(("implicit", "offset"), [(False, 0.0), (True, 5.0)])
def test_fold_in_matches_spark_user_factors(spark, implicit, offset):
    ratings = _ratings()
    model, users = _spark_model(spark, ratings, implicit, offset)
    for user_id, part in ratings.groupby("user_id"):
        vec = fold_in(model, part["anime_id"].to_numpy(), part["score"].to_numpy())
        # Jeu jouet tiré avec une seed fixe : chaque utilisateur a au moins une note > neutre,
        # sinon le fold-in implicite renverrait None (cas testé à part).
        assert vec is not None
        expected = np.asarray(users.loc[user_id, "features"])
        # Spark calcule en float32 : tolérance relative à la norme du vecteur.
        assert np.allclose(vec, expected, atol=1e-3 * max(1.0, np.linalg.norm(expected)))
