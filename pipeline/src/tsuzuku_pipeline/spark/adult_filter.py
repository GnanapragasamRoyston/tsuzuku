"""Exclusion des contenus adultes, appliquée au catalogue puis à toutes les interactions."""

from typing import Any

from pyspark.sql import Column, DataFrame
from pyspark.sql import functions as F


def flag_adult(catalog: DataFrame, rules: dict[str, Any]) -> DataFrame:
    """Ajoute `is_adult` : rating commençant par un préfixe interdit OU genre interdit.

    Les deux règles sont nécessaires : dans le dataset, 3 animes ont le genre Hentai sans rating Rx.
    Un rating inconnu (null) ne suffit pas à exclure : on n'a aucune preuve que l'œuvre est adulte.
    """
    banned = F.array(*[F.lit(g) for g in rules["genres"]])
    by_genre = F.coalesce(F.size(F.array_intersect("genres", banned)) > 0, F.lit(False))
    return catalog.withColumn("is_adult", adult_by_rating(rules["rating_prefixes"]) | by_genre)


def adult_by_rating(prefixes: list[str]) -> Column:
    """Vrai si `rating` commence par un des préfixes ; faux (jamais null) si rating est inconnu.

    Partagé avec le rapport qualité : la règle mesurée doit être exactement la règle appliquée.
    """
    condition = F.lit(False)
    for prefix in prefixes:
        condition = condition | F.coalesce(F.col("rating").startswith(prefix), F.lit(False))
    return condition


def filter_by_catalog(interactions: DataFrame, allowed_ids: DataFrame) -> DataFrame:
    """Garde uniquement les interactions dont l'anime est dans le catalogue autorisé.

    Semi-jointure plutôt qu'anti-jointure sur la liste des adultes : elle exclut du même coup les
    anime_id orphelins (absents d'anime.csv), dont on ne peut pas vérifier qu'ils sont tout public.
    broadcast : le catalogue (~16 000 ids) est copié sur chaque tâche, ce qui évite de trier et
    redistribuer les 109 M lignes d'interactions (shuffle) pour la jointure.
    """
    kept = interactions.join(F.broadcast(allowed_ids.select("anime_id")), "anime_id", "left_semi")
    # La jointure place la clé en tête : on restaure l'ordre d'origine (schéma stable en aval).
    return kept.select(interactions.columns)
