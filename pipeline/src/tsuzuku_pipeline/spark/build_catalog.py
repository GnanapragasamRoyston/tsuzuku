"""Lignes du catalogue anime pour Postgres (catalog.media, catalog.genre, catalog.media_genre).

Source : la couche clean (contenus adultes déjà exclus). Les colonnes agrégées de MAL (dropped,
completed, score_*...) ne vont PAS dans le catalogue : elles ne servent pas à l'appli et on évite
qu'elles soient réutilisées par erreur comme features (fuite, ADR 002).
"""

from pyspark.sql import DataFrame
from pyspark.sql import functions as F

# Ordre = ordre des colonnes du COPY dans le loader, où la liste est définie (le loader est aussi
# importé sans PySpark par l'ingestion). Les colonnes de catalog.media absentes ici (anilist_id,
# chapters, airing_status, cover_url) viennent de Jikan et AniList (phase 6).
from tsuzuku_pipeline.db.loader import MEDIA_COLUMNS  # noqa: F401  (ré-exporté)


def media_rows(anime: DataFrame, synopsis: DataFrame) -> DataFrame:
    return anime.join(synopsis.select("anime_id", "synopsis"), "anime_id", "left").select(
        F.lit("anime").alias("kind"),
        F.col("anime_id").alias("mal_id"),
        F.col("name").alias("title"),
        F.col("english_name").alias("title_alt"),
        "synopsis",
        "episodes",
        F.col("type").alias("format"),
        "duration_min",
        "start_year",
        # « studios ou auteurs » (SPEC § 5) : studios pour un anime, auteurs pour un manga.
        F.col("studios").alias("creators"),
        "source",
        F.col("rating").alias("age_rating"),
        "popularity",
    )


def media_genres(anime: DataFrame) -> DataFrame:
    """Paires (mal_id, genre) ; les ids Postgres seront résolus au chargement."""
    return anime.select(
        F.col("anime_id").alias("mal_id"), F.explode("genres").alias("genre")
    ).distinct()
