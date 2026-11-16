"""Rétention par genre et par studio (marts `retention_by_genre`, `retention_by_studio`)."""

from dataclasses import dataclass

from pyspark.sql import DataFrame
from pyspark.sql import functions as F


@dataclass(frozen=True)
class StatusCodes:
    """Codes de watching_status, lus dans la table de référence (jamais en dur dans le calcul)."""

    watching: int
    completed: int
    on_hold: int
    dropped: int

    @classmethod
    def from_reference(cls, rows: dict[str, int]) -> "StatusCodes":
        return cls(
            watching=rows["Currently Watching"],
            completed=rows["Completed"],
            on_hold=rows["On Hold"],
            dropped=rows["Dropped"],
        )


def retention_by(
    animelist: DataFrame,
    anime: DataFrame,
    group_col: str,
    name: str,
    codes: StatusCodes,
    min_interactions: int,
    min_anime: int,
) -> DataFrame:
    """Taux de drop, taux de complétion et progression médiane au drop, par valeur de `group_col`.

    - drop_rate = dropped / (dropped + completed) ;
    - completion_rate = completed / commencés (watching + completed + on hold + dropped). Plan to
      Watch est exclu : la personne n'a pas commencé. Ce n'est donc PAS 1 - drop_rate ;
    - median_drop_progress = médiane de watched / episodes sur les drops (episodes connu).

    Ordre des calculs : on agrège d'abord par anime (~16 000 lignes), puis on « explose » les
    genres. Exploser les 107 M lignes d'abord multiplierait le volume par ~3 pour rien.
    Seule la médiane a besoin des lignes individuelles (une médiane ne s'additionne pas) :
    on l'approxime avec percentile_approx sur les seuls drops.
    """
    started = [codes.watching, codes.completed, codes.on_hold, codes.dropped]
    status = F.col("watching_status")
    per_anime = animelist.groupBy("anime_id").agg(
        F.sum(F.when(status == codes.completed, 1).otherwise(0)).alias("c"),
        F.sum(F.when(status == codes.dropped, 1).otherwise(0)).alias("d"),
        F.sum(F.when(status.isin(started), 1).otherwise(0)).alias("s"),
    )
    groups = F.broadcast(anime.select("anime_id", "episodes", F.explode(group_col).alias(name)))

    counts = (
        per_anime.where("c + d > 0")
        .join(groups, "anime_id")
        .groupBy(name)
        .agg(
            F.countDistinct("anime_id").alias("nb_anime"),
            F.sum("c").alias("nb_completed"),
            F.sum("d").alias("nb_dropped"),
            F.sum("s").alias("nb_started"),
        )
    )

    progress = F.least(F.greatest("watched_episodes", F.lit(0)), "episodes") / F.col("episodes")
    medians = (
        animelist.where(status == codes.dropped)
        .join(groups.where("episodes > 0"), "anime_id")
        .groupBy(name)
        .agg(F.percentile_approx(progress, 0.5, 10000).alias("median_drop_progress"))
    )

    interactions = F.col("nb_completed") + F.col("nb_dropped")
    return (
        counts.where((interactions >= min_interactions) & (F.col("nb_anime") >= min_anime))
        .join(medians, name, "left")
        .select(
            name,
            "nb_anime",
            "nb_completed",
            "nb_dropped",
            (F.col("nb_dropped") / interactions).alias("drop_rate"),
            (F.col("nb_completed") / F.col("nb_started")).alias("completion_rate"),
            "median_drop_progress",
        )
    )
