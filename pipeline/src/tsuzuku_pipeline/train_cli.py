"""Point d'entrée de `make train` (phase 3) : features → fit → register.

- features : Spark calcule les features sur les 71 M lignes Completed/Dropped
             (data/features/drop_all), puis tire l'échantillon d'utilisateurs (drop_sample).
- fit      : scikit-learn — split par utilisateur, 3 modèles, grille, seuil, évaluation sur le
             test, figures, artefact + fiche (models/), reports/drop_metrics.json.
- register : ajoute le run dans mart.model_runs (idempotent par run_id).
Même logique de fraîcheur que `make data` / `make spark` (sorties + empreinte de config).
"""

import argparse
import hashlib
import json
import logging
import uuid
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import sklearn
from pyspark.sql import SparkSession
from pyspark.sql import functions as F

from tsuzuku_pipeline.config import load_settings, require_section, resolve_path
from tsuzuku_pipeline.data_cli import stamp_dir
from tsuzuku_pipeline.db import loader
from tsuzuku_pipeline.ml.drop.evaluate import (
    classification_metrics,
    permutation_ranking,
    plot_calibration,
    plot_curves,
    plot_importance,
    reliability,
)
from tsuzuku_pipeline.ml.drop.export import artifact_paths, save_artifact, verify_artifact
from tsuzuku_pipeline.ml.drop.features import feature_columns, spark_drop_features
from tsuzuku_pipeline.ml.drop.train import (
    MODEL_KINDS,
    TARGET,
    calibrate_isotonic,
    choose_threshold,
    prepare_x,
    select_models,
    split_by_user,
)
from tsuzuku_pipeline.spark.sample import sample_users
from tsuzuku_pipeline.spark.session import build_spark
from tsuzuku_pipeline.spark_cli import status_codes
from tsuzuku_pipeline.steps import Step, fingerprint, write_parquet

logger = logging.getLogger("tsuzuku_pipeline.train")

STEPS = ("features", "fit", "register")


def _features_dir(s: dict[str, Any]) -> Path:
    return resolve_path(s, "features")


def _genres_file(s: dict[str, Any]) -> Path:
    return _features_dir(s) / "drop_genres.json"


def _clean(s: dict[str, Any], name: str) -> Path:
    return resolve_path(s, "parquet") / "clean" / name


# --- features (Spark) --------------------------------------------------------------------------


def _build_features(spark: SparkSession, settings: dict[str, Any]) -> None:
    cfg = require_section(settings, "drop_model")
    out = _features_dir(settings)
    anime = spark.read.parquet(str(_clean(settings, "anime")))
    animelist = spark.read.parquet(str(_clean(settings, "animelist")))

    # Vocabulaire des genres figé à l'entraînement et enregistré : l'API devra utiliser exactement
    # la même liste, dans le même ordre (colonnes du modèle).
    genres = sorted(r[0] for r in anime.select(F.explode("genres")).distinct().collect())
    features = spark_drop_features(animelist, anime, status_codes(spark, settings), genres)
    write_parquet(features, out / "drop_all")

    sample = sample_users(
        spark.read.parquet(str(out / "drop_all")),
        cfg["sample_user_fraction"],
        settings["project"]["seed"],
    )
    write_parquet(sample, out / "drop_sample")
    _genres_file(settings).write_text(json.dumps(genres, ensure_ascii=False), encoding="utf-8")


# --- fit (scikit-learn) ------------------------------------------------------------------------


def data_fingerprint(settings: dict[str, Any]) -> str:
    """Empreinte des données brutes (manifest sha256 des CSV) + de la config du modèle."""
    manifest = resolve_path(settings, "raw") / "manifest.json"
    if manifest.is_file():
        raw = manifest.read_bytes()
    else:
        # Traçabilité dégradée : on continue (tests, données hors Kaggle) mais on le dit.
        logger.warning("%s absent : empreinte de données basée sur la config seule", manifest)
        raw = b"no-manifest"
    config = fingerprint(
        {"drop_model": require_section(settings, "drop_model"), "seed": settings["project"]["seed"]}
    )
    return hashlib.sha256(raw + config.encode()).hexdigest()


def _build_fit(_spark: SparkSession | None, settings: dict[str, Any]) -> None:
    cfg = require_section(settings, "drop_model")
    seed = settings["project"]["seed"]
    genres = json.loads(_genres_file(settings).read_text(encoding="utf-8"))
    df = pd.read_parquet(_features_dir(settings) / "drop_sample")
    logger.info("Échantillon : %d lignes, %d utilisateurs", len(df), df["user_id"].nunique())

    split = split_by_user(df, cfg["val_fraction"], cfg["test_fraction"], seed)
    best = select_models(split, cfg, genres, seed)
    for kind, cand in best.items():
        logger.info("%s : PR-AUC validation %.4f %s", kind, cand.val_pr_auc, cand.params)

    # Modèle final choisi sur la VALIDATION (jamais sur le test). La baseline n'est pas candidate.
    final_kind = max(("logreg", "hgb"), key=lambda k: best[k].val_pr_auc)
    final_model, threshold_set = best[final_kind].pipeline, split.val
    if cfg["calibration"] == "isotonic":
        final_model, threshold_set = calibrate_isotonic(final_model, split.val, genres, seed)
    elif cfg["calibration"] != "none":
        raise ValueError(f"calibration inconnue : {cfg['calibration']!r} (none | isotonic)")

    def proba(model: Any, part: pd.DataFrame) -> np.ndarray:
        return model.predict_proba(prepare_x(part, genres))[:, 1]

    models = {k: (final_model if k == final_kind else best[k].pipeline) for k in MODEL_KINDS}
    thresholds = {
        k: choose_threshold(
            (threshold_set if k == final_kind else split.val)[TARGET].to_numpy(),
            proba(models[k], threshold_set if k == final_kind else split.val),
        )
        for k in MODEL_KINDS
    }

    # Test : évalué une seule fois, pour les 3 modèles, avec les seuils fixés sur la validation.
    y_test = split.test[TARGET].to_numpy()
    test_probas = {k: proba(models[k], split.test) for k in MODEL_KINDS}
    test_metrics = {
        k: classification_metrics(y_test, test_probas[k], thresholds[k]) for k in MODEL_KINDS
    }
    bins, _ = reliability(y_test, test_probas[final_kind])
    ranking = permutation_ranking(
        models[final_kind],
        prepare_x(split.test, genres),
        split.test[TARGET],
        n_rows=cfg["permutation_rows"],
        n_repeats=cfg["permutation_repeats"],
        seed=seed,
    )

    figures = resolve_path(settings, "reports") / "figures"
    plot_curves(y_test, test_probas, figures)
    plot_calibration(bins, final_kind, figures / "calibration.png")
    plot_importance(ranking, figures / "importance.png")

    run_id, created_at = str(uuid.uuid4()), datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    data = {
        "rows": len(df),
        "users": int(df["user_id"].nunique()),
        "splits": {
            name: {
                "rows": len(part),
                "users": int(part["user_id"].nunique()),
                "prevalence": float(part[TARGET].mean()),
            }  # fmt: skip
            for name, part in (("train", split.train), ("val", split.val), ("test", split.test))
        },
    }
    report = {
        "generated_at": created_at,
        "run_id": run_id,
        "data": data,
        "selection": {k: {"params": c.params, "val_pr_auc": c.val_pr_auc} for k, c in best.items()},
        "final_model": final_kind,
        "calibration": cfg["calibration"],
        "test": test_metrics,
        "calibration_bins_test": bins,
        "permutation_importance_test": ranking,
    }
    reports = resolve_path(settings, "reports")
    (reports / "drop_metrics.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    # Nombre d'itérations réellement faites : avec l'arrêt précoce (« auto » de sklearn), il peut
    # être inférieur à max_iter ; on enregistre la valeur effective, pas seulement la consigne.
    estimator = best[final_kind].pipeline.named_steps["model"]
    effective = (
        {"n_iter_effective": int(estimator.n_iter_)} if hasattr(estimator, "n_iter_") else {}
    )
    card = {
        "run_id": run_id,
        "created_at": created_at,
        "model_name": "drop",
        "model_type": final_kind,
        "params": {**best[final_kind].params, **effective, "calibration": cfg["calibration"]},
        "threshold": thresholds[final_kind],
        "genres": genres,
        "feature_columns": feature_columns(genres),
        "metrics": {"test": test_metrics[final_kind]},
        "data_fingerprint": data_fingerprint(settings),
        "versions": {"scikit-learn": sklearn.__version__},
    }
    # save_artifact complète la fiche : chemin de la copie du run + sha256 de l'artefact.
    save_artifact(final_model, card, resolve_path(settings, "models"))
    logger.info(
        "Modèle final : %s — PR-AUC test %.4f (baseline %.4f)",
        final_kind,
        test_metrics[final_kind]["pr_auc"],
        test_metrics["dummy"]["pr_auc"],
    )


# --- register (Postgres) -----------------------------------------------------------------------


def _build_register(_spark: SparkSession | None, settings: dict[str, Any]) -> None:
    # verify_artifact : on n'enregistre qu'un couple modèle/fiche cohérent (sha256 vérifié),
    # sans désérialiser le pickle.
    card = verify_artifact(resolve_path(settings, "models"))
    run = {f: card[f] for f in loader.MODEL_RUN_FIELDS}
    url = loader.database_url()
    with loader.connect(url) as conn:
        loader.apply_schemas(conn)
        loader.insert_model_run(conn, run)


def _fit_config(s: dict[str, Any]) -> dict[str, Any]:
    cfg = dict(require_section(s, "drop_model"))
    cfg.pop("sample_user_fraction", None)  # concerne l'étape features
    return {"drop_model": cfg, "seed": s["project"]["seed"]}


STEP_DEFS = {
    "features": Step(
        "train_features",
        inputs=lambda s: [_clean(s, n) for n in ("anime", "animelist", "watching_status")],
        outputs=lambda s: [
            _features_dir(s) / "drop_all",
            _features_dir(s) / "drop_sample",
            _genres_file(s),
        ],
        build=_build_features,
        config=lambda s: {
            "fraction": require_section(s, "drop_model")["sample_user_fraction"],
            "seed": s["project"]["seed"],
        },
        stamp_dir=stamp_dir,
    ),
    "fit": Step(
        "train_fit",
        inputs=lambda s: [_features_dir(s) / "drop_sample", _genres_file(s)],
        outputs=lambda s: [
            resolve_path(s, "reports") / "drop_metrics.json",
            *artifact_paths(resolve_path(s, "models")),
        ],
        build=_build_fit,
        config=_fit_config,
        stamp_dir=stamp_dir,
    ),
    "register": Step(
        "train_register",
        inputs=lambda s: [],
        outputs=lambda s: [],
        build=_build_register,
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

    # Spark n'est démarré que si l'étape features doit vraiment tourner (fit et register n'en
    # ont pas besoin) : relancer `make train` pour réentraîner ne paie pas le démarrage d'une JVM.
    feats = STEP_DEFS["features"]
    needs_spark = "features" in steps and (force or not feats.is_up_to_date(settings))
    owns_session = needs_spark and spark is None
    if owns_session:
        spark = build_spark(settings, app_name="tsuzuku-train")
    try:
        for name in STEPS:
            if name in steps:
                STEP_DEFS[name].run(spark, settings, force)
    finally:
        if owns_session:
            spark.stop()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Phase 3 : modèle de drop.")
    parser.add_argument("--step", action="append", choices=STEPS, help="Étape(s), répétable.")
    parser.add_argument("--force", action="store_true", help="Refait même si à jour.")
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s | %(message)s"
    )
    run(load_settings(), steps=args.step or STEPS, force=args.force)


if __name__ == "__main__":
    main()
