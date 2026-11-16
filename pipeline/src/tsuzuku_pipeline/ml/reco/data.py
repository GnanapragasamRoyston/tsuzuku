"""Préparation des notes pour l'ALS (Spark) : filtre d'activité, split par utilisateur, masquage.

Tous les tirages sont des HACHAGES (xxhash64 de l'identifiant + seed + un « sel » propre au
tirage), pas des `sample()` : le résultat ne dépend ni du partitionnement ni de la machine, et les
tirages sont indépendants entre eux (le sel évite que le split recoupe l'échantillon de dev).
"""

import logging

from pyspark.sql import Column, DataFrame
from pyspark.sql import functions as F

logger = logging.getLogger("tsuzuku_pipeline.reco")

_BUCKETS = 1_000_000


def _bucket(*cols: Column) -> Column:
    """Nombre pseudo-aléatoire stable dans [0, 1) à partir des colonnes données."""
    return F.pmod(F.xxhash64(*cols), F.lit(_BUCKETS)) / F.lit(float(_BUCKETS))


def user_bucket(salt: str, seed: int) -> Column:
    return _bucket(F.col("user_id"), F.lit(seed), F.lit(salt))


def filter_active(
    ratings: DataFrame, min_user_ratings: int, min_item_ratings: int, max_rounds: int = 10
) -> tuple[DataFrame, int]:
    """Garde les utilisateurs et animes assez actifs, en ITÉRANT jusqu'à stabilité.

    Retirer un anime peu noté peut faire passer un utilisateur sous son seuil, et inversement :
    une seule passe laisserait des lignes sous les seuils. Renvoie (notes, nombre de passes).
    """
    if min_user_ratings < 1 or min_item_ratings < 1:
        raise ValueError("chaque seuil d'activité doit valoir au moins 1")
    current = ratings
    previous = current.count()
    for round_ in range(1, max_rounds + 1):
        users = current.groupBy("user_id").count().where(F.col("count") >= min_user_ratings)
        items = current.groupBy("anime_id").count().where(F.col("count") >= min_item_ratings)
        nxt = (
            current.join(items.select("anime_id"), "anime_id", "left_semi")
            .join(users.select("user_id"), "user_id", "left_semi")
            .cache()
        )
        n = nxt.count()
        logger.info("Filtre d'activité, passe %d : %d → %d notes", round_, previous, n)
        if current is not ratings:
            current.unpersist()
        if n == previous:
            return nxt.select(*ratings.columns), round_
        current, previous = nxt, n
    raise RuntimeError(f"filtre d'activité non stable après {max_rounds} passes")


def assign_split(
    ratings: DataFrame, val_fraction: float, test_fraction: float, seed: int
) -> DataFrame:
    """Ajoute `split` (train / val / test), décidé PAR UTILISATEUR.

    Les utilisateurs de validation et de test ne sont jamais vus par l'ALS : on les évalue comme
    de nouveaux utilisateurs Tsuzuku, via le fold-in.
    """
    if val_fraction <= 0 or test_fraction <= 0 or val_fraction + test_fraction >= 1:
        raise ValueError("fractions val/test invalides : chacune > 0 et somme < 1")
    b = user_bucket("reco_split", seed)
    split = (
        F.when(b < test_fraction, "test")
        .when(b < test_fraction + val_fraction, "val")
        .otherwise("train")
    )
    return ratings.withColumn("split", split)


def mask_holdout(df: DataFrame, mask_fraction: float, seed: int) -> DataFrame:
    """Ajoute `masked` : pour les utilisateurs val/test, la part de notes à retrouver.

    Masquage aléatoire (par couple utilisateur-anime) : le dataset n'a pas de dates, un masquage
    « les dernières notes » est impossible. Les lignes de train ne sont jamais masquées.
    """
    if not 0 < mask_fraction < 1:
        raise ValueError(f"mask_fraction doit être dans ]0, 1[, reçu {mask_fraction}")
    b = _bucket(F.col("user_id"), F.col("anime_id"), F.lit(seed), F.lit("reco_mask"))
    return df.withColumn("masked", (F.col("split") != "train") & (b < mask_fraction))
