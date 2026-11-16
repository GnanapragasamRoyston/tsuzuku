"""Point d'entrée de `make data` : download → staging → clean → quality → sample.

Couches (ADR 002) :
- data/raw/              CSV Kaggle tels quels + manifest.json (sha256)
- data/parquet/staging/  CSV typés, NON filtrés : fidèles à la source, base du rapport qualité
- data/parquet/clean/    filtrés (clés nulles, statuts inconnus, doublons, adulte, orphelins) :
                         seule entrée des phases 2 à 4
- data/samples/          sous-ensemble d'utilisateurs de clean, pour itérer vite en dev

Idempotence « à la make » : une étape est sautée si ses sorties sont complètes ET plus récentes
que ses entrées. Refaire clean rend donc automatiquement quality et sample périmés.
--force refait tout. Limite : un changement de settings.yaml n'est pas détecté → --force.
"""

import argparse
import json
import logging
from collections.abc import Callable, Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as F

from tsuzuku_pipeline.config import load_settings, require_section, resolve_path
from tsuzuku_pipeline.ingestion.kaggle_download import download_dataset
from tsuzuku_pipeline.spark import quality_checks as qc
from tsuzuku_pipeline.spark.adult_filter import filter_by_catalog, flag_adult
from tsuzuku_pipeline.spark.clean import clean_interactions
from tsuzuku_pipeline.spark.sample import sample_users
from tsuzuku_pipeline.spark.session import build_spark
from tsuzuku_pipeline.spark.to_parquet import (
    clean_anime,
    clean_synopsis,
    read_anime,
    read_interactions,
    read_synopsis,
    read_watching_status,
)

logger = logging.getLogger("tsuzuku_pipeline.data")

STEPS = ("download", "staging", "clean", "quality", "sample")
INTERACTION_TABLES = ("animelist", "rating_complete")
CATALOG_TABLES = ("anime", "synopsis", "watching_status")
RAW_FILES = {
    "anime": "anime.csv",
    "synopsis": "anime_with_synopsis.csv",
    "watching_status": "watching_status.csv",
    "animelist": "animelist.csv",
    "rating_complete": "rating_complete.csv",
}


# --- Fraîcheur des sorties -------------------------------------------------------------------


def _marker(path: Path) -> Path:
    # Pour un dossier Parquet, _SUCCESS est écrit par Spark en toute fin d'écriture : son absence
    # signale une sortie partielle (job interrompu). Pour un fichier, c'est le fichier lui-même.
    return path / "_SUCCESS" if path.suffix == "" else path


def _is_fresh(outputs: Iterable[Path], inputs: Iterable[Path]) -> bool:
    markers = [_marker(p) for p in outputs]
    if not all(m.is_file() for m in markers):
        return False
    sources = [_marker(p) for p in inputs if _marker(p).is_file()]
    if not sources:
        return True
    return min(m.stat().st_mtime_ns for m in markers) >= max(s.stat().st_mtime_ns for s in sources)


def _write(df: DataFrame, path: Path) -> None:
    df.write.mode("overwrite").parquet(str(path))
    logger.info("Écrit %s", path)


# --- Étapes ----------------------------------------------------------------------------------


class Step:
    """Une étape : ses entrées, ses sorties, et la fonction qui les produit."""

    def __init__(
        self,
        name: str,
        inputs: Callable[[dict], list[Path]],
        outputs: Callable[[dict], list[Path]],
        build: Callable[[SparkSession, dict], None],
    ) -> None:
        self.name, self.inputs, self.outputs, self.build = name, inputs, outputs, build

    def run(self, spark: SparkSession, settings: dict[str, Any], force: bool) -> None:
        if not force and _is_fresh(self.outputs(settings), self.inputs(settings)):
            logger.info("Étape %s : à jour, ignorée (--force pour refaire)", self.name)
            return
        logger.info("=== Étape %s ===", self.name)
        self.build(spark, settings)


def _layer(settings: dict[str, Any], layer: str) -> Path:
    return resolve_path(settings, "parquet") / layer


def _build_staging(spark: SparkSession, settings: dict[str, Any]) -> None:
    raw, out = resolve_path(settings, "raw"), _layer(settings, "staging")
    readers = {
        "anime": lambda p: clean_anime(read_anime(spark, p)),
        "synopsis": lambda p: clean_synopsis(read_synopsis(spark, p)),
        "watching_status": lambda p: read_watching_status(spark, p),
        "animelist": lambda p: read_interactions(spark, p, with_status=True),
        "rating_complete": lambda p: read_interactions(spark, p, with_status=False),
    }
    for name, read in readers.items():
        _write(read(raw / RAW_FILES[name]), out / name)


def _valid_statuses(spark: SparkSession, settings: dict[str, Any]) -> dict[int, str]:
    """Codes lus dans watching_status.csv, jamais supposés (le code 5 n'existe pas)."""
    rows = spark.read.parquet(str(_layer(settings, "staging") / "watching_status")).collect()
    # Une ligne illisible (status null) est ignorée : elle ne définit aucun code valide.
    return {r["status"]: r["description"] for r in rows if r["status"] is not None}


def _build_clean(spark: SparkSession, settings: dict[str, Any]) -> None:
    rules = require_section(settings, "data")["adult_filter"]
    staging, out = _layer(settings, "staging"), _layer(settings, "clean")

    def read(name: str) -> DataFrame:
        return spark.read.parquet(str(staging / name))

    allowed = flag_adult(read("anime"), rules).where(~F.col("is_adult")).drop("is_adult")
    statuses = list(_valid_statuses(spark, settings))
    _write(allowed, out / "anime")
    _write(filter_by_catalog(read("synopsis"), allowed), out / "synopsis")
    _write(read("watching_status").dropna(subset=["status"]), out / "watching_status")
    _write(clean_interactions(read("animelist"), allowed, statuses), out / "animelist")
    _write(clean_interactions(read("rating_complete"), allowed), out / "rating_complete")


def build_quality_report(spark: SparkSession, settings: dict[str, Any]) -> dict[str, Any]:
    data = require_section(settings, "data")

    def read(layer: str, name: str) -> DataFrame:
        return spark.read.parquet(str(_layer(settings, layer) / name))

    catalog = flag_adult(read("staging", "anime"), data["adult_filter"])
    statuses = _valid_statuses(spark, settings)
    animelist, rating = read("staging", "animelist"), read("staging", "rating_complete")
    synopsis = read("staging", "synopsis").agg(
        F.count(F.lit(1)).alias("rows"),
        F.sum(F.when(F.col("synopsis").isNull(), 1).otherwise(0)).alias("missing_synopsis"),
    )

    return {
        "generated_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "dataset": data["kaggle_dataset"],
        "license": data["license"],
        "watching_status": {str(k): v for k, v in sorted(statuses.items())},
        "tables": {
            "anime": qc.catalog_metrics(catalog, data["adult_filter"]["rating_prefixes"]),
            "synopsis": {k: int(v or 0) for k, v in synopsis.first().asDict().items()},
            "animelist": qc.interaction_metrics(
                animelist, (0, 10), statuses, catalog.select("anime_id", "episodes")
            ),
            "rating_complete": qc.interaction_metrics(rating, (1, 10)),
        },
        "filters": {
            "anime": {
                "rows_before": catalog.count(),
                "rows_after": read("clean", "anime").count(),
            },
            "animelist": qc.filter_metrics(
                animelist, read("clean", "animelist"), catalog, valid_statuses=list(statuses)
            ),
            "rating_complete": qc.filter_metrics(rating, read("clean", "rating_complete"), catalog),
        },
        "consistency": {
            "rating_complete_pairs_missing_from_animelist": qc.pairs_missing_from(rating, animelist)
        },
    }


def _build_quality(spark: SparkSession, settings: dict[str, Any]) -> None:
    reports = resolve_path(settings, "reports")
    report = build_quality_report(spark, settings)
    reports.mkdir(parents=True, exist_ok=True)
    (reports / "data_quality.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    (reports / "data_quality.md").write_text(qc.render_markdown(report), encoding="utf-8")
    logger.info("Rapport qualité écrit dans %s", reports)


def _build_sample(spark: SparkSession, settings: dict[str, Any]) -> None:
    fraction = require_section(settings, "data")["sample_user_fraction"]
    seed = settings["project"]["seed"]
    clean, out = _layer(settings, "clean"), resolve_path(settings, "samples")
    for name in INTERACTION_TABLES:
        _write(sample_users(spark.read.parquet(str(clean / name)), fraction, seed), out / name)


def _tables(settings: dict, layer: str, names: Iterable[str]) -> list[Path]:
    return [_layer(settings, layer) / n for n in names]


ALL_TABLES = (*CATALOG_TABLES, *INTERACTION_TABLES)
SPARK_STEPS = {
    "staging": Step(
        "staging",
        inputs=lambda s: [resolve_path(s, "raw") / f for f in RAW_FILES.values()],
        outputs=lambda s: _tables(s, "staging", ALL_TABLES),
        build=_build_staging,
    ),
    "clean": Step(
        "clean",
        inputs=lambda s: _tables(s, "staging", ALL_TABLES),
        outputs=lambda s: _tables(s, "clean", ALL_TABLES),
        build=_build_clean,
    ),
    "quality": Step(
        "quality",
        inputs=lambda s: _tables(s, "staging", ALL_TABLES) + _tables(s, "clean", ALL_TABLES),
        outputs=lambda s: [resolve_path(s, "reports") / "data_quality.json"],
        build=_build_quality,
    ),
    "sample": Step(
        "sample",
        inputs=lambda s: _tables(s, "clean", INTERACTION_TABLES),
        outputs=lambda s: [resolve_path(s, "samples") / n for n in INTERACTION_TABLES],
        build=_build_sample,
    ),
}


def run(
    settings: dict[str, Any],
    steps: Iterable[str] = STEPS,
    force: bool = False,
    api: Any = None,
    spark: SparkSession | None = None,
) -> None:
    """Lance les étapes demandées, dans l'ordre de STEPS. `api`/`spark` injectables (tests)."""
    steps = list(steps)
    unknown = sorted(set(steps) - set(STEPS))
    if unknown:
        raise ValueError(f"Étapes inconnues : {', '.join(unknown)} (attendu : {', '.join(STEPS)})")

    if "download" in steps:
        data = require_section(settings, "data")
        download_dataset(
            data["kaggle_dataset"],
            data["files"],
            resolve_path(settings, "raw"),
            api=api,
            force=force,
        )

    todo = [SPARK_STEPS[s] for s in STEPS if s in steps and s in SPARK_STEPS]
    if not todo:
        return
    owns_session = spark is None
    spark = spark or build_spark(settings, app_name="tsuzuku-data")
    try:
        for step in todo:
            step.run(spark, settings, force)
    finally:
        if owns_session:
            spark.stop()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Phase 1 : préparation des données Kaggle.")
    parser.add_argument(
        "--step",
        action="append",
        choices=STEPS,
        help="Étape(s) à lancer (répétable). Par défaut : toutes.",
    )
    parser.add_argument("--force", action="store_true", help="Refait les étapes demandées.")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s | %(message)s"
    )
    run(load_settings(), steps=args.step or STEPS, force=args.force)


if __name__ == "__main__":
    main()
