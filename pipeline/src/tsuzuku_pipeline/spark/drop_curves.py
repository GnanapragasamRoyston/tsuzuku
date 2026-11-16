"""Courbes de drop, épisode critique, point de non-retour (marts drop_curve, critical_episode).

Population : uniquement les lignes Completed et Dropped, les seules dont l'issue est connue.
Les spectateurs encore en cours (Watching, On Hold) sont ignorés : c'est une « censure à droite »,
limite assumée et documentée (README, ADR 003).
"""

from pyspark.sql import DataFrame, Window
from pyspark.sql import functions as F


def outcomes(animelist: DataFrame, anime: DataFrame, completed: int, dropped: int) -> DataFrame:
    """Une ligne par (utilisateur, anime) terminé ou lâché, avec l'épisode atteint.

    `reached` :
    - Completed → `episodes` : le statut fait foi. Des centaines de milliers de lignes Completed ont
      un watched_episodes inférieur au total (liste pas mise à jour), ce n'est pas un vrai arrêt.
      Si episodes est inconnu, on garde watched_episodes.
    - Dropped → watched_episodes plafonné à `episodes` (certaines lignes le dépassent).
    """
    df = animelist.where(F.col("watching_status").isin(completed, dropped)).join(
        F.broadcast(anime.select("anime_id", "episodes")), "anime_id"
    )
    is_dropped = F.col("watching_status") == dropped
    watched = F.greatest(F.col("watched_episodes"), F.lit(0))
    capped = F.when(F.col("episodes").isNull(), watched).otherwise(
        F.least(watched, F.col("episodes"))
    )
    reached = F.when(is_dropped, capped).otherwise(F.coalesce(F.col("episodes"), watched))
    return df.select(
        "anime_id", "episodes", is_dropped.alias("is_dropped"), reached.alias("reached")
    )


def drop_curve(outs: DataFrame) -> DataFrame:
    """Drops par épisode et part cumulée (de 0 à 1) pour chaque anime.

    L'épisode 0 (lâché avant de commencer) est gardé : c'est une information produit utile
    (« X % abandonnent avant le 1er épisode »), même s'il est exclu de l'épisode critique.
    """
    counts = (
        outs.where("is_dropped")
        .groupBy("anime_id", F.col("reached").alias("episode"))
        .agg(F.count(F.lit(1)).alias("nb_drops"))
    )
    by_anime = Window.partitionBy("anime_id")
    cumulative = by_anime.orderBy("episode").rowsBetween(Window.unboundedPreceding, 0)
    return counts.withColumn(
        "cumulative_share",
        F.sum("nb_drops").over(cumulative) / F.sum("nb_drops").over(by_anime),
    )


def critical_episodes(
    outs: DataFrame, risk_ratio: float, min_drops: int, min_episodes: int
) -> DataFrame:
    """Épisode critique et point de non-retour, pour les animes avec assez de données.

    - épisode critique : l'épisode ≥ 1 qui concentre le plus de drops (égalité → le plus tôt).
      Les drops à 0 sont exclus : sinon « épisode critique = 0 » pour une grande part du catalogue,
      ce qui ne dit rien sur le contenu de l'œuvre.
    - risque de lâcher pour qui a atteint e : risk(e) = drops avec reached ≥ e /
      (completed + ces drops). initial_drop_risk = risk(1).
    - point de non-retour : 1er épisode e où risk(e) ≤ risk_ratio × risk(1).
      Définition RELATIVE (choisie par Royston, ADR 003) : sur MAL, les utilisateurs déclarent
      ~16 fois plus de Completed que de Dropped, donc un seuil absolu de complétion (ex. 90 %)
      était atteint dès l'épisode 1 pour la majorité des animes. Comparer l'anime à lui-même
      neutralise cette sous-déclaration. risk(e) ne fait que baisser quand e avance (moins de
      drops restants) : le premier e qui passe le seuil suffit.
    """
    if not 0 < risk_ratio < 1:
        raise ValueError(f"risk_ratio doit être dans ]0, 1[, reçu {risk_ratio}")
    # ≥ 1 : sequence(1, 0) produirait un épisode 0, et sans drop à e=1 le risque initial serait
    # une division par zéro.
    if min_drops < 1 or min_episodes < 1:
        raise ValueError(
            f"min_drops et min_episodes doivent être ≥ 1, reçus {min_drops} et {min_episodes}"
        )
    per_anime = outs.groupBy("anime_id").agg(
        F.first("episodes").alias("episodes"),
        F.sum(F.when(~F.col("is_dropped"), 1).otherwise(0)).alias("nb_completed"),
        F.sum(F.when(F.col("is_dropped"), 1).otherwise(0)).alias("nb_drops"),
        F.sum(F.when(F.col("is_dropped") & (F.col("reached") >= 1), 1).otherwise(0)).alias(
            "nb_drops_started"
        ),
    )
    eligible = per_anime.where(
        F.col("episodes").isNotNull()
        & (F.col("episodes") >= min_episodes)
        & (F.col("nb_drops_started") >= min_drops)
    )

    drops_at = (
        outs.where("is_dropped")
        .groupBy("anime_id", "reached")
        .agg(F.count(F.lit(1)).alias("n"))
        .join(eligible.select("anime_id"), "anime_id", "left_semi")
    )

    # Épisode critique : rang 1 par anime sur (nb de drops décroissant, épisode croissant).
    rank = Window.partitionBy("anime_id").orderBy(F.desc("n"), F.asc("reached"))
    critical = (
        drops_at.where("reached >= 1")
        .withColumn("rank", F.row_number().over(rank))
        .where("rank = 1")
        .select("anime_id", F.col("reached").alias("critical_episode"), F.col("n").alias("n_crit"))
    )

    # Point de non-retour : on déroule e = 1..episodes et on compte les drops avec reached ≥ e.
    # Volume : somme des épisodes des animes éligibles (quelques dizaines de milliers de lignes).
    grid = eligible.select(
        "anime_id", "nb_completed", F.explode(F.sequence(F.lit(1), "episodes")).alias("e")
    )
    survivors_drops = (
        grid.join(drops_at, "anime_id")
        .where(F.col("reached") >= F.col("e"))
        .groupBy("anime_id", "e")
        .agg(F.sum("n").alias("drops_ge"))
    )
    # min_drops ≥ 1 garantit au moins un drop à e=1 : le dénominateur n'est jamais nul.
    risk = (
        grid.join(survivors_drops, ["anime_id", "e"], "left")
        .withColumn("drops_ge", F.coalesce("drops_ge", F.lit(0)))
        .withColumn("risk", F.col("drops_ge") / (F.col("nb_completed") + F.col("drops_ge")))
    )
    initial = risk.where("e = 1").select("anime_id", F.col("risk").alias("initial_drop_risk"))
    no_return = (
        risk.join(initial, "anime_id")
        .where(F.col("risk") <= F.lit(risk_ratio) * F.col("initial_drop_risk"))
        .groupBy("anime_id")
        .agg(F.min("e").alias("point_of_no_return"))
    )

    return (
        eligible.join(critical, "anime_id")
        .join(initial, "anime_id")
        .join(no_return, "anime_id", "left")
        .select(
            "anime_id",
            "critical_episode",
            (F.col("n_crit") / F.col("nb_drops_started")).alias("critical_drop_share"),
            "initial_drop_risk",
            "point_of_no_return",
            "nb_drops",
            "nb_completed",
            (F.col("nb_drops") / (F.col("nb_drops") + F.col("nb_completed"))).alias("drop_rate"),
        )
    )
