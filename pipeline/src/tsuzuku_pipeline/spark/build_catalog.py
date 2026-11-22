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


def _title_key(col: str):
    """Même règle que records.title_key : lettres et chiffres ASCII, en minuscules."""
    return F.regexp_replace(F.lower(F.col(col)), "[^0-9a-z]", "")


def _distinct_english():
    """Titre anglais présent ET vraiment différent (pas seulement la ponctuation)."""
    return F.col("english_name").isNotNull() & (_title_key("english_name") != _title_key("name"))


def media_rows(anime: DataFrame, synopsis: DataFrame) -> DataFrame:
    return anime.join(synopsis.select("anime_id", "synopsis"), "anime_id", "left").select(
        F.lit("anime").alias("kind"),
        F.col("anime_id").alias("mal_id"),
        # Titre anglais d'abord, celui que tout le monde connaît (« Attack on Titan » et non
        # « Shingeki no Kyojin ») ; le romaji reste en titre secondaire (cherchable). Même règle
        # que l'ingestion (records.display_titles).
        # Titres qui ne diffèrent que par la ponctuation ou les espaces : l'original est gardé.
        F.when(_distinct_english(), F.col("english_name")).otherwise(F.col("name")).alias("title"),
        F.when(_distinct_english(), F.col("name")).alias("title_alt"),
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
