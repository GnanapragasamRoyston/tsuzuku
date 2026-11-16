"""Échantillon de développement : un sous-ensemble d'utilisateurs, avec TOUTES leurs lignes."""

from pyspark.sql import DataFrame
from pyspark.sql import functions as F

_BUCKETS = 1_000_000


def sample_users(df: DataFrame, fraction: float, seed: int) -> DataFrame:
    """Garde les utilisateurs dont le hachage (user_id, seed) tombe sous `fraction`.

    Pourquoi pas `df.sample()` : il tire des LIGNES, ce qui casserait l'historique d'un utilisateur
    (taux de drop, split par utilisateur en phase 3). Et son résultat dépend du partitionnement.
    Le hachage décide utilisateur par utilisateur, de façon stable : même seed → mêmes
    utilisateurs, dans animelist comme dans rating_complete, sur n'importe quelle machine.
    """
    if not 0 < fraction <= 1:
        raise ValueError(f"fraction doit être dans ]0, 1], reçu {fraction}")
    bucket = F.pmod(F.xxhash64(F.col("user_id"), F.lit(seed)), F.lit(_BUCKETS))
    return df.where(bucket < int(fraction * _BUCKETS))
