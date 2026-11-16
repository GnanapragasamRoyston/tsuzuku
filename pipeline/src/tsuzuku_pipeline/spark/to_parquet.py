"""Lecture des CSV Kaggle et typage : CSV brut → couche staging (Parquet typé, non filtré).

Choix clés (ADR 002) :
- schémas explicites : `inferSchema` relirait les 109 M lignes une fois de plus juste pour deviner
  les types, et pourrait se tromper ;
- mode PERMISSIVE : une valeur illisible devient null au lieu de faire planter le job ou de
  disparaître en silence ; le rapport qualité compte ensuite ces nulls.
"""

from pathlib import Path

from pyspark.sql import Column, DataFrame, SparkSession
from pyspark.sql import functions as F
from pyspark.sql.types import IntegerType, StringType, StructField, StructType

# Options CSV communes : le dataset double les guillemets ("") pour les échapper, à la RFC 4180.
CSV_OPTIONS = {"header": "true", "escape": '"', "mode": "PERMISSIVE", "encoding": "UTF-8"}

# Colonnes d'anime.csv dans l'ordre du fichier → nom snake_case. Spark lit par position.
ANIME_COLUMNS = {
    "MAL_ID": "anime_id",
    "Name": "name",
    "Score": "mal_score",
    "Genres": "genres",
    "English name": "english_name",
    "Japanese name": "japanese_name",
    "Type": "type",
    "Episodes": "episodes",
    "Aired": "aired",
    "Premiered": "premiered",
    "Producers": "producers",
    "Licensors": "licensors",
    "Studios": "studios",
    "Source": "source",
    "Duration": "duration",
    "Rating": "rating",
    "Ranked": "ranked",
    "Popularity": "popularity",
    "Members": "members",
    "Favorites": "favorites",
    "Watching": "watching",
    "Completed": "completed",
    "On-Hold": "on_hold",
    "Dropped": "dropped",
    "Plan to Watch": "plan_to_watch",
    **{f"Score-{i}": f"score_{i}" for i in range(10, 0, -1)},
}
LIST_COLUMNS = ["genres", "producers", "licensors", "studios"]
INT_COLUMNS = [
    "anime_id", "episodes", "popularity", "members", "favorites",
    "watching", "completed", "on_hold", "dropped", "plan_to_watch",
]  # fmt: skip
# Ranked et Score-N sont écrits "28.0" dans le fichier : on passe par double avant l'entier.
FLOAT_AS_INT_COLUMNS = ["ranked", *[f"score_{i}" for i in range(10, 0, -1)]]

_INTERACTIONS = [
    StructField("user_id", IntegerType()),
    StructField("anime_id", IntegerType()),
    StructField("score", IntegerType()),  # "rating" dans le CSV ; 0 = non noté dans animelist
]
_STATUS = [
    StructField("watching_status", IntegerType()),
    StructField("watched_episodes", IntegerType()),
]  # noqa: E501


def _all_strings(names) -> StructType:
    return StructType([StructField(n, StringType()) for n in names])


def _read(
    spark: SparkSession, path: Path, schema: StructType, multiline: bool = False
) -> DataFrame:
    # multiLine n'est activé que pour les synopsis : il empêche Spark de découper le fichier en
    # morceaux lus en parallèle, ce qui serait très lent sur les 2 Go d'animelist.
    return (
        spark.read.options(**CSV_OPTIONS)
        .option("multiLine", str(multiline).lower())
        .schema(schema)
        .csv(str(path))
    )


def read_anime(spark: SparkSession, path: Path) -> DataFrame:
    # Tout en texte d'abord : les colonnes numériques contiennent "Unknown", qu'on traite à la main.
    return _read(spark, path, _all_strings(ANIME_COLUMNS.values()))


def read_interactions(spark: SparkSession, path: Path, with_status: bool) -> DataFrame:
    """animelist.csv (with_status=True) ou rating_complete.csv (with_status=False)."""
    fields = _INTERACTIONS + (_STATUS if with_status else [])
    return _read(spark, path, StructType(fields))


def read_watching_status(spark: SparkSession, path: Path) -> DataFrame:
    # L'en-tête réel est "status, description" (espace parasite) : on impose nos propres noms.
    schema = StructType(
        [StructField("status", IntegerType()), StructField("description", StringType())]
    )
    return _read(spark, path, schema).withColumn("description", F.trim("description"))


def read_synopsis(spark: SparkSession, path: Path) -> DataFrame:
    # "sypnopsis" : faute de frappe dans le fichier source, corrigée par le renommage.
    names = ["anime_id", "name", "mal_score", "genres", "synopsis"]
    return _read(spark, path, _all_strings(names), multiline=True)


def _unknown_to_null(c: Column) -> Column:
    trimmed = F.trim(c)
    return F.when((trimmed == "Unknown") | (trimmed == ""), None).otherwise(trimmed)


def _to_list(c: Column) -> Column:
    # Liste vide plutôt que null : le multi-hot des genres (phase 3) n'aura pas de cas spécial.
    return F.coalesce(F.split(c, r",\s*"), F.array().cast("array<string>"))


def _extract_int(c: Column, pattern: str) -> Column:
    value = F.regexp_extract(c, pattern, 1)
    return F.when(value == "", None).otherwise(value.cast("int"))


def duration_minutes(c: Column) -> Column:
    """'24 min. per ep.', '1 hr. 55 min.', '30 sec.' → minutes (par épisode si 'per ep.')."""
    hours = F.coalesce(_extract_int(c, r"(\d+) hr"), F.lit(0))
    minutes = F.coalesce(_extract_int(c, r"(\d+) min"), F.lit(0))
    seconds = F.coalesce(_extract_int(c, r"(\d+) sec"), F.lit(0))
    total = hours * 60 + minutes + seconds / 60.0
    return F.when(c.isNull() | (total == 0), None).otherwise(total.cast("double"))


def clean_anime(raw: DataFrame) -> DataFrame:
    df = raw.select([_unknown_to_null(F.col(c)).alias(c) for c in raw.columns])
    for c in LIST_COLUMNS:
        df = df.withColumn(c, _to_list(F.col(c)))
    for c in INT_COLUMNS:
        df = df.withColumn(c, F.col(c).cast("int"))
    for c in FLOAT_AS_INT_COLUMNS:
        df = df.withColumn(c, F.col(c).cast("double").cast("int"))
    return (
        df.withColumn("mal_score", F.col("mal_score").cast("double"))
        .withColumn("duration_min", duration_minutes(F.col("duration")))
        # Premiered est absent pour ~73 % des animes ; l'année d'Aired couvre aussi les films/OVA.
        .withColumn("start_year", _extract_int(F.col("aired"), r"(\d{4})"))
        .withColumn(
            "premiered_season",
            F.nullif(F.regexp_extract("premiered", r"^(Winter|Spring|Summer|Fall)", 1), F.lit("")),
        )
    )


def clean_synopsis(raw: DataFrame) -> DataFrame:
    return raw.select(
        F.col("anime_id").cast("int").alias("anime_id"),
        _unknown_to_null(F.col("synopsis")).alias("synopsis"),
    )
