"""Règles de passage staging → clean pour les tables d'interactions."""

from collections.abc import Iterable

from pyspark.sql import DataFrame
from pyspark.sql import functions as F

from tsuzuku_pipeline.spark.adult_filter import filter_by_catalog

KEYS = ["user_id", "anime_id"]


def clean_interactions(
    df: DataFrame, allowed_ids: DataFrame, valid_statuses: Iterable[int] | None = None
) -> DataFrame:
    """Retire, dans cet ordre (le même que filter_metrics, pour que les comptes collent) :
    1. les clés nulles (valeur illisible dans le CSV) ;
    2. les statuts absents de watching_status.csv (0, 5, 33, 55 dans le dataset réel) : sans
       sens connu, ils fausseraient le taux de drop ;
    3. les doublons EXACTS : une même ligne écrite deux fois n'apporte aucune information.
       On ne dédoublonne pas sur la seule clé, ce qui choisirait une ligne au hasard ;
    4. les animes adultes et orphelins (semi-jointure sur le catalogue autorisé).
    """
    df = df.dropna(subset=KEYS)
    if valid_statuses is not None:
        df = df.where(F.col("watching_status").isin(list(valid_statuses)))
    return filter_by_catalog(df.dropDuplicates(), allowed_ids)
