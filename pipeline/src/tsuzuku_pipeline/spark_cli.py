"""Point d'entrée de `make spark` (phase 2) : marts → load.

- marts : Spark calcule, sur data/parquet/clean, les courbes de drop, épisodes critiques et
  statistiques de rétention → data/marts/<table> (Parquet) + reports/marts_summary.json.
  Sautée si à jour (même logique de fraîcheur que `make data`).
- load  : applique le DDL, upsert du catalogue anime, puis remplace chaque mart dans Postgres.
  Tourne à chaque fois : l'état de la base ne se lit pas dans un fichier (elle a pu être recréée).
"""

import argparse
import json
import logging
import shutil
from collections.abc import Iterable, Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as F

from tsuzuku_pipeline.config import load_settings, require_section, resolve_path
from tsuzuku_pipeline.data_cli import stamp_dir
from tsuzuku_pipeline.db import loader
from tsuzuku_pipeline.spark.build_catalog import MEDIA_COLUMNS, media_genres, media_rows
from tsuzuku_pipeline.spark.drop_curves import critical_episodes, drop_curve, outcomes
from tsuzuku_pipeline.spark.retention_stats import StatusCodes, retention_by
from tsuzuku_pipeline.spark.session import build_spark
from tsuzuku_pipeline.steps import Step, write_parquet

logger = logging.getLogger("tsuzuku_pipeline.spark")

STEPS = ("marts", "load")
MART_TABLES = tuple(loader.MARTS)
# Entrées des marts (synopsis n'en fait pas partie : seul le chargement du catalogue l'utilise).
CLEAN_INPUTS = ("anime", "watching_status", "animelist")


def _clean(settings: dict[str, Any], name: str) -> Path:
    return resolve_path(settings, "parquet") / "clean" / name


def status_codes(spark: SparkSession, settings: dict[str, Any]) -> StatusCodes:
    """Codes lus dans la table de référence, par libellé : jamais de « 4 = Dropped » en dur."""
    rows = spark.read.parquet(str(_clean(settings, "watching_status"))).collect()
    return StatusCodes.from_reference({r["description"]: r["status"] for r in rows})


def compute_marts(spark: SparkSession, settings: dict[str, Any]) -> dict[str, DataFrame]:
    crit = require_section(settings, "critical_episode")
    ret = require_section(settings, "retention")
    codes = status_codes(spark, settings)
    anime = spark.read.parquet(str(_clean(settings, "anime")))
    animelist = spark.read.parquet(str(_clean(settings, "animelist")))

    # outcomes est relu par deux calculs : on le garde en cache plutôt que de rejoindre
    # deux fois 107 M lignes (il ne fait que quelques dizaines de Mo une fois filtré).
    outs = outcomes(animelist, anime, codes.completed, codes.dropped).cache()
    common = {"min_interactions": ret["min_interactions"], "min_anime": ret["min_anime"]}
    return {
        "drop_curve": drop_curve(outs).select("anime_id", *loader.MARTS["drop_curve"]["columns"]),
        "critical_episode": critical_episodes(
            outs,
            risk_ratio=crit["no_return_risk_ratio"],
            min_drops=crit["min_drops"],
            min_episodes=crit["min_episodes"],
        ).select("anime_id", *loader.MARTS["critical_episode"]["columns"]),
        "retention_by_genre": retention_by(
            animelist, anime, "genres", "genre", codes, **common
        ).select(*loader.MARTS["retention_by_genre"]["columns"]),
        "retention_by_studio": retention_by(
            animelist, anime, "studios", "studio", codes, **common
        ).select(*loader.MARTS["retention_by_studio"]["columns"]),
    }


def summarize(marts: dict[str, DataFrame]) -> dict[str, Any]:
    """Comptes et contrôles de cohérence : toute anomalie > 0 signale un bug de calcul."""
    curve, crit = marts["drop_curve"], marts["critical_episode"]
    last_share = curve.groupBy("anime_id").agg(F.max("cumulative_share").alias("m"))
    crit_stats = crit.agg(
        F.count(F.lit(1)).alias("anime"),
        F.count("point_of_no_return").alias("with_point_of_no_return"),
    ).first()
    rate_cols = {"retention_by_genre": "genre", "retention_by_studio": "studio"}
    return {
        "generated_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "drop_curve": {
            "rows": curve.count(),
            "anime": curve.select("anime_id").distinct().count(),
        },
        "critical_episode": {
            "anime": crit_stats["anime"],
            "with_point_of_no_return": crit_stats["with_point_of_no_return"],
        },
        **{name: {"rows": marts[name].count()} for name in rate_cols},
        "checks": {
            # La part cumulée doit finir exactement à 1 pour chaque anime.
            "curves_not_ending_at_1": last_share.where(F.abs(F.col("m") - 1) > 1e-9).count(),
            "rates_out_of_range": sum(
                marts[n]
                .where(~F.col("drop_rate").between(0, 1) | ~F.col("completion_rate").between(0, 1))
                .count()
                for n in rate_cols
            ),
        },
    }


def _build_marts(spark: SparkSession, settings: dict[str, Any]) -> None:
    out = resolve_path(settings, "marts")
    marts = compute_marts(spark, settings)
    for name, df in marts.items():
        write_parquet(df, out / name)
    # Le résumé relit les Parquet écrits : il décrit exactement ce qui sera chargé.
    written = {n: spark.read.parquet(str(out / n)) for n in marts}
    summary = summarize(written)
    reports = resolve_path(settings, "reports")
    reports.mkdir(parents=True, exist_ok=True)
    (reports / "marts_summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    bad = failed_checks(summary)
    if bad:
        # Les Parquet incohérents sont supprimés : le prochain run les recalculera au lieu de les
        # croire « à jour » et de les charger (le tampon de config n'est pas écrit non plus).
        for name in marts:
            shutil.rmtree(out / name, ignore_errors=True)
        logger.error("Contrôles de cohérence en échec : %s", bad)
        raise RuntimeError(f"Marts incohérents, chargement bloqué : {bad}")


def failed_checks(summary: dict[str, Any]) -> dict[str, int]:
    return {k: v for k, v in summary.get("checks", {}).items() if v}


def _tuples(df: DataFrame, columns: Iterable[str]) -> Iterator[tuple]:
    # toLocalIterator : les lignes arrivent par partition, jamais toutes en mémoire du driver,
    # et en types Python natifs (int, float, list) que psycopg sait écrire sans conversion.
    for row in df.select(*columns).toLocalIterator():
        yield tuple(row)


def _check_summary_before_load(settings: dict[str, Any]) -> None:
    """Deuxième barrière : on ne charge jamais des marts dont le résumé signale une anomalie."""
    path = resolve_path(settings, "reports") / "marts_summary.json"
    try:
        summary = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise RuntimeError(f"{path} absent ou illisible : relance l'étape marts") from None
    bad = failed_checks(summary)
    if bad:
        raise RuntimeError(f"Marts incohérents d'après {path.name}, chargement bloqué : {bad}")


def _build_load(spark: SparkSession, settings: dict[str, Any]) -> None:
    _check_summary_before_load(settings)
    url = loader.database_url()
    logger.info("Chargement vers %s", loader.describe(url))
    anime = spark.read.parquet(str(_clean(settings, "anime")))
    synopsis = spark.read.parquet(str(_clean(settings, "synopsis")))
    marts_dir = resolve_path(settings, "marts")

    with loader.connect(url) as conn:
        # UNE transaction pour tout le chargement (les transactions du loader deviennent des
        # savepoints) : si un mart échoue, catalogue et marts restent tous dans l'état précédent,
        # l'API et Power BI ne lisent jamais un mélange d'ancienne et de nouvelle version.
        with conn.transaction():
            loader.apply_schemas(conn)
            # Le catalogue d'abord : les marts y sont rattachés par clé étrangère.
            loader.upsert_media(
                conn,
                _tuples(media_rows(anime, synopsis), MEDIA_COLUMNS),
                _tuples(media_genres(anime), ("mal_id", "genre")),
            )
            for name, spec in loader.MARTS.items():
                df = spark.read.parquet(str(marts_dir / name))
                cols = ("anime_id", *spec["columns"]) if spec["by_media"] else spec["columns"]
                loader.replace_mart(conn, name, _tuples(df, cols))


def _marts_config(settings: dict[str, Any]) -> dict[str, Any]:
    return {
        "critical_episode": require_section(settings, "critical_episode"),
        "retention": require_section(settings, "retention"),
    }


SPARK_STEPS = {
    "marts": Step(
        "marts",
        inputs=lambda s: [_clean(s, n) for n in CLEAN_INPUTS],
        outputs=lambda s: (
            [resolve_path(s, "marts") / n for n in MART_TABLES]
            + [resolve_path(s, "reports") / "marts_summary.json"]
        ),
        build=_build_marts,
        # Changer un seuil dans settings.yaml rend les marts périmés (sans --force).
        config=_marts_config,
        stamp_dir=stamp_dir,
    ),
    "load": Step(
        "load",
        inputs=lambda s: [resolve_path(s, "marts") / n for n in MART_TABLES],
        outputs=lambda s: [],
        build=_build_load,
        always=True,
    ),
}


def run(
    settings: dict[str, Any],
    steps: Iterable[str] = STEPS,
    force: bool = False,
    spark: SparkSession | None = None,
) -> None:
    steps = list(steps)
    unknown = sorted(set(steps) - set(STEPS))
    if unknown:
        raise ValueError(f"Étapes inconnues : {', '.join(unknown)} (attendu : {', '.join(STEPS)})")
    owns_session = spark is None
    spark = spark or build_spark(settings, app_name="tsuzuku-spark")
    try:
        for name in STEPS:
            if name in steps:
                SPARK_STEPS[name].run(spark, settings, force)
    finally:
        if owns_session:
            spark.stop()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Phase 2 : marts Spark → Postgres.")
    parser.add_argument("--step", action="append", choices=STEPS, help="Étape(s), répétable.")
    parser.add_argument("--force", action="store_true", help="Recalcule même si à jour.")
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s | %(message)s"
    )
    run(load_settings(), steps=args.step or STEPS, force=args.force)


if __name__ == "__main__":
    main()
