"""Métriques de qualité des données, calculées sur les couches staging et clean.

Chaque fonction renvoie un dict de types Python simples (int, str) : sérialisable tel quel dans
reports/data_quality.json, qui est la seule source autorisée pour les chiffres du README.
"""

from typing import Any

from pyspark.sql import DataFrame
from pyspark.sql import functions as F

from tsuzuku_pipeline.spark.adult_filter import adult_by_rating
from tsuzuku_pipeline.spark.clean import KEYS


def _count_if(condition) -> F.Column:
    return F.sum(F.when(condition, 1).otherwise(0))


def interaction_metrics(
    df: DataFrame,
    score_range: tuple[int, int],
    statuses: dict[int, str] | None = None,
    episodes: DataFrame | None = None,
) -> dict[str, Any]:
    """Métriques d'une table d'interactions (animelist ou rating_complete).

    Les lignes à clé nulle sont comptées puis exclues des autres métriques : elles seront retirées
    à l'étape clean, inutile de les compter deux fois.
    """
    total = df.count()
    valid = df.where(F.col("user_id").isNotNull() & F.col("anime_id").isNotNull())
    low, high = score_range

    # Un seul passage sur les données pour toutes les métriques simples.
    exprs = [
        F.count(F.lit(1)).alias("valid_rows"),
        F.countDistinct("user_id").alias("distinct_users"),
        F.countDistinct("anime_id").alias("distinct_anime"),
        _count_if((F.col("score") < low) | (F.col("score") > high)).alias("score_out_of_range"),
        _count_if(F.col("score") == 0).alias("score_zero"),
        _count_if(F.col("score").isNull()).alias("score_null"),
    ]
    if statuses is not None:
        exprs += [
            _count_if(F.col("watched_episodes") < 0).alias("negative_watched_episodes"),
            # coalesce : `NOT isin` vaut NULL (pas TRUE) pour un statut null, qui serait oublié.
            _count_if(
                F.coalesce(~F.col("watching_status").isin(list(statuses)), F.lit(True))
            ).alias("unknown_status_rows"),
        ]
    agg = valid.agg(*exprs).first().asDict()

    duplicates = (
        valid.groupBy(KEYS).count().where("count > 1").agg(F.sum(F.col("count") - 1)).first()[0]
    )
    metrics: dict[str, Any] = {
        "rows": total,
        "null_keys": total - agg.pop("valid_rows"),
        "duplicate_pairs": int(duplicates or 0),
        **{k: int(v or 0) for k, v in agg.items()},
    }

    if statuses is not None:
        counts = valid.groupBy("watching_status").count().collect()
        metrics["status_counts"] = {
            statuses.get(r["watching_status"], f"unknown({r['watching_status']})"): r["count"]
            for r in sorted(counts, key=lambda r: -r["count"])
        }
    if episodes is not None:
        joined = valid.join(F.broadcast(episodes.select("anime_id", "episodes")), "anime_id")
        metrics["watched_gt_episodes"] = joined.where(
            F.col("episodes").isNotNull() & (F.col("watched_episodes") > F.col("episodes"))
        ).count()
    return metrics


def catalog_metrics(catalog: DataFrame, rating_prefixes: list[str]) -> dict[str, Any]:
    """Catalogue d'animes (staging, avec la colonne is_adult)."""
    by_rating = adult_by_rating(rating_prefixes)
    scalar_cols = [f.name for f in catalog.schema.fields if not f.dataType.typeName() == "array"]
    agg = (
        catalog.agg(
            F.count(F.lit(1)).alias("rows"),
            (F.count(F.lit(1)) - F.countDistinct("anime_id")).alias("duplicate_anime_ids"),
            _count_if(F.col("is_adult")).alias("adult_total"),
            _count_if(F.col("is_adult") & ~by_rating).alias("adult_by_genre_only"),
            _count_if(F.col("rating").isNull()).alias("unknown_rating"),
            _count_if(F.size("genres") == 0).alias("empty_genres"),
            *[_count_if(F.col(c).isNull()).alias(f"null__{c}") for c in scalar_cols],
        )
        .first()
        .asDict()
    )

    nulls = {k.removeprefix("null__"): int(v) for k, v in agg.items() if k.startswith("null__")}
    metrics = {k: int(v) for k, v in agg.items() if not k.startswith("null__")}
    metrics["null_counts"] = {k: v for k, v in nulls.items() if v}
    return metrics


def filter_metrics(
    staging: DataFrame,
    clean: DataFrame,
    catalog: DataFrame,
    valid_statuses: list[int] | None = None,
) -> dict[str, int]:
    """Ventilation des lignes retirées entre staging et clean.

    Rejoue les étapes de clean_interactions dans le même ordre (clé nulle → statut inconnu →
    doublon exact → adulte/orphelin) : la somme des retraits égale donc exactement
    rows_before - rows_after, ce que vérifient les tests.
    """
    rows_before = staging.count()
    step = staging.dropna(subset=KEYS)
    after_keys = step.count()
    if valid_statuses is not None:
        step = step.where(F.col("watching_status").isin(list(valid_statuses)))
    after_status = step.count()
    step = step.dropDuplicates()
    after_dedup = step.count()

    # dropDuplicates sur le catalogue : un anime_id en double multiplierait les lignes jointes.
    flags = F.broadcast(catalog.select("anime_id", "is_adult").dropDuplicates(["anime_id"]))
    by_reason = (
        step.join(flags, "anime_id", "left")
        .agg(
            _count_if(F.col("is_adult")).alias("removed_adult"),
            _count_if(F.col("is_adult").isNull()).alias("removed_orphan"),
            F.countDistinct(F.when(F.col("is_adult").isNull(), F.col("anime_id"))).alias(
                "orphan_anime_ids"
            ),
        )
        .first()
    )
    return {
        "rows_before": rows_before,
        "removed_null_keys": rows_before - after_keys,
        "removed_unknown_status": after_keys - after_status,
        "removed_duplicates": after_status - after_dedup,
        "removed_adult": int(by_reason["removed_adult"] or 0),
        "removed_orphan": int(by_reason["removed_orphan"] or 0),
        "orphan_anime_ids": int(by_reason["orphan_anime_ids"] or 0),
        "rows_after": clean.count(),
    }


def pairs_missing_from(left: DataFrame, right: DataFrame) -> int:
    """Nombre de paires (user_id, anime_id) de `left` absentes de `right`.

    Sert à vérifier que rating_complete est bien un sous-ensemble d'animelist.
    """
    return left.select(KEYS).join(right.select(KEYS).distinct(), KEYS, "left_anti").count()


def _fmt(value: Any) -> str:
    # Séparateur de milliers à la française (espace) : 1 234 567.
    if isinstance(value, int) and not isinstance(value, bool):
        return f"{value:,}".replace(",", " ")
    return str(value)


def _table(d: dict[str, Any]) -> list[str]:
    lines = ["| Métrique | Valeur |", "|---|---:|"]
    for key, value in d.items():
        if isinstance(value, dict):
            for sub, v in value.items():
                lines.append(f"| {key} · {sub} | {_fmt(v)} |")
        else:
            lines.append(f"| {key} | {_fmt(value)} |")
    return lines


def render_markdown(report: dict[str, Any]) -> str:
    """Version lisible du rapport JSON (même contenu, aucun chiffre ajouté)."""
    lines = [
        "# Rapport qualité des données",
        "",
        f"Généré le {report['generated_at']} depuis `reports/data_quality.json`.",
        f"Source : Kaggle `{report['dataset']}` · licence {report['license']}.",
        "",
    ]
    for name, metrics in report.get("tables", {}).items():
        lines += [f"## Table `{name}` (staging)", "", *_table(metrics), ""]
    for name, metrics in report.get("filters", {}).items():
        lines += [f"## Filtrage `{name}` (staging → clean)", "", *_table(metrics), ""]
    for name, value in report.get("consistency", {}).items():
        lines += [f"- **{name}** : {_fmt(value)}"]
    return "\n".join(lines).rstrip() + "\n"
