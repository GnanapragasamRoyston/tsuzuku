"""Point d'entrée de `make reco` (phase 4) : prepare → fit → register.

- prepare  : Spark — filtre d'activité itératif sur rating_complete, split par utilisateur,
             masquage des notes à retrouver (data/features/reco/{train,holdout}).
- fit      : grille ALS (explicite et implicite) sur une part du train, évaluée par fold-in sur
             des utilisateurs de validation ; les meilleurs sont réentraînés sur tout le train ;
             choix final sur la validation, test évalué une seule fois ; figures, exemples,
             reports/reco_metrics.json, facteurs exportés (models/).
- register : ajoute le run dans mart.model_runs (idempotent par run_id).
"""

import argparse
import dataclasses
import json
import logging
import os
import shutil
import subprocess
import time
import uuid
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pyspark
from pyspark.sql import SparkSession
from pyspark.sql import functions as F
from tsuzuku_ml.fold_in import (
    FoldInModel,
    fold_in,
    onboarding_ratings,
    recommend,
    top_k_positions,
)

from tsuzuku_pipeline.config import REPO_ROOT, load_settings, require_section, resolve_path
from tsuzuku_pipeline.data_cli import stamp_dir
from tsuzuku_pipeline.db import loader
from tsuzuku_pipeline.ml.reco.data import assign_split, filter_active, mask_holdout, user_bucket
from tsuzuku_pipeline.ml.reco.evaluate import (
    evaluate_users,
    onboarding_profile,
    plot_at_k,
    plot_grid,
    plot_onboarding,
    shrunk_item_means,
)
from tsuzuku_pipeline.ml.reco.evaluate import rmse as rmse_fn
from tsuzuku_pipeline.ml.reco.export import reco_paths, save_reco_artifact, verify_reco_artifact
from tsuzuku_pipeline.ml.reco.train import (
    KINDS,
    GridPoint,
    als_predictor,
    als_scorer,
    fit_als,
    grid_points,
    item_stats,
    popularity_scores,
)
from tsuzuku_pipeline.spark.session import build_spark, spark_conf
from tsuzuku_pipeline.steps import Step, write_parquet
from tsuzuku_pipeline.train_cli import data_fingerprint

logger = logging.getLogger("tsuzuku_pipeline.reco")

STEPS = ("prepare", "fit", "register")


def _reco_dir(s: dict[str, Any]) -> Path:
    return resolve_path(s, "features") / "reco"


def _prepare_stats(s: dict[str, Any]) -> Path:
    return _reco_dir(s) / "prepare_stats.json"


def _clean(s: dict[str, Any], name: str) -> Path:
    return resolve_path(s, "parquet") / "clean" / name


# --- prepare (Spark) ---------------------------------------------------------------------------


def _build_prepare(spark: SparkSession, settings: dict[str, Any]) -> None:
    cfg, seed = require_section(settings, "reco"), settings["project"]["seed"]
    ratings = spark.read.parquet(str(_clean(settings, "rating_complete")))
    before = ratings.count()
    filtered, rounds = filter_active(ratings, cfg["min_user_ratings"], cfg["min_item_ratings"])
    df = mask_holdout(
        assign_split(filtered, cfg["val_fraction"], cfg["test_fraction"], seed),
        cfg["mask_fraction"],
        seed,
    )
    out = _reco_dir(settings)
    write_parquet(df.where("split = 'train'").select("user_id", "anime_id", "score"), out / "train")
    write_parquet(
        df.where("split != 'train'").select("user_id", "anime_id", "score", "split", "masked"),
        out / "holdout",
    )

    written = spark.read.parquet(str(out / "train")).withColumn("split", F.lit("train"))
    holdout = spark.read.parquet(str(out / "holdout"))
    per_split = {
        r["split"]: {"rows": r["rows"], "users": r["users"], "masked": r["masked"]}
        for r in written.select("user_id", "split", F.lit(False).alias("masked"))
        .unionByName(holdout.select("user_id", "split", "masked"))
        .groupBy("split")
        .agg(
            F.count("*").alias("rows"),
            F.countDistinct("user_id").alias("users"),
            F.sum(F.col("masked").cast("int")).alias("masked"),
        )
        .collect()
    }
    stats = {
        "rows_before": before,
        "rows_after": filtered.count(),
        "users_after": filtered.select("user_id").distinct().count(),
        "anime_after": filtered.select("anime_id").distinct().count(),
        "filter_rounds": rounds,
        "splits": per_split,
    }
    _prepare_stats(settings).write_text(json.dumps(stats, indent=2) + "\n", encoding="utf-8")
    logger.info("Préparation : %s", stats)


# --- fit (Spark ALS + NumPy) -------------------------------------------------------------------


def _sample_users(part: pd.DataFrame, n: int, seed: int) -> pd.DataFrame:
    users = np.sort(part["user_id"].unique())
    if len(users) <= n:
        return part
    chosen = np.random.default_rng(seed).choice(users, size=n, replace=False)
    return part[part["user_id"].isin(chosen)]


def _showcase(
    settings: dict[str, Any], model: FoldInModel, popularity: np.ndarray, default_score: float
) -> dict[str, Any]:
    """Exemple commenté : profil fictif « a aimé les titres vitrines » → top 10 par fold-in."""
    titles = settings.get("key_figures", {}).get("showcase_titles", [])
    anime = pd.read_parquet(_clean(settings, "anime"), columns=["anime_id", "name"])
    names = anime.set_index("anime_id")["name"]
    liked = anime[anime["name"].isin(titles)]["anime_id"].tolist()
    if not liked:
        return {}
    ids, scores = onboarding_ratings(liked, {}, default_score)
    vec = fold_in(model, ids, scores)
    top = recommend(model, vec, exclude=liked, k=10) if vec is not None else np.array([])
    pop_top = model.item_ids[top_k_positions(popularity, model.positions(liked), 10)]
    return {
        "liked": [names.get(a, str(a)) for a in liked],
        "liked_ids": [int(a) for a in liked],
        "default_score": default_score,
        "recommended": [names.get(int(a), str(a)) for a in top],
        "recommended_ids": [int(a) for a in top],
        "popularity_top10": [names.get(int(a), str(a)) for a in pop_top],
        "shared_with_popularity": len(set(top.tolist()) & set(pop_top.tolist())),
    }


def _git_sha() -> str | None:
    """Commit du code qui a produit le run (traçabilité), None hors dépôt git."""
    git = shutil.which("git")  # chemin complet : pas de résolution implicite par le PATH
    if git is None:
        return None
    try:
        # Arguments fixes, aucune entrée utilisateur : pas d'injection possible.
        out = subprocess.run(  # noqa: S603
            [git, "rev-parse", "HEAD"], cwd=REPO_ROOT, capture_output=True, text=True, check=True
        )
        dirty = subprocess.run(  # noqa: S603
            [git, "status", "--porcelain"], cwd=REPO_ROOT, capture_output=True, text=True
        ).stdout.strip()
        # « -dirty » : le code exécuté contient des changements non commités.
        return out.stdout.strip() + ("-dirty" if dirty else "")
    except (OSError, subprocess.CalledProcessError):
        return None


def _write_json_atomic(path: Path, doc: dict[str, Any]) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def _on_grid_edge(best: dict[str, Any], cfg: dict[str, Any]) -> bool:
    """Vrai si le meilleur point touche une borne de la grille : l'optimum n'est pas encadré."""
    return best["rank"] in (min(cfg["ranks"]), max(cfg["ranks"])) or best["reg_param"] in (
        min(cfg["reg_params"]),
        max(cfg["reg_params"]),
    )


def _ndcg(res: dict[str, Any], k: int) -> float:
    value = res["at_k"][str(k)]["ndcg"]
    if value is None:
        raise RuntimeError("aucun utilisateur classé : NDCG indéfinie, sélection impossible")
    return value


def _build_fit(spark: SparkSession, settings: dict[str, Any]) -> None:
    cfg, seed = require_section(settings, "reco"), settings["project"]["seed"]
    rel, k_sel, ks = cfg["relevant_min_score"], cfg["selection_k"], cfg["k_values"]
    # Checkpoint sur disque : ALS coupe régulièrement sa lignée (sinon StackOverflow sur les
    # longues chaînes d'itérations). Même dossier disque que les déversements de Spark.
    spark.sparkContext.setCheckpointDir(str(Path(spark_conf(settings)["spark.local.dir"]) / "ckpt"))

    reco = _reco_dir(settings)
    train = spark.read.parquet(str(reco / "train")).cache()
    holdout = pd.read_parquet(reco / "holdout")
    val, test = holdout[holdout["split"] == "val"], holdout[holdout["split"] == "test"]
    stats = item_stats(train, rel)
    global_mean = float(stats["sum"].sum() / stats["count"].sum())
    means = shrunk_item_means(stats, global_mean, cfg["baseline_shrinkage"])

    # 1. Grille : une part des utilisateurs du train, évaluée sur un sous-ensemble de validation.
    grid_train = train.where(user_bucket("reco_grid", seed) < cfg["grid_user_fraction"]).cache()
    grid_val = _sample_users(val, cfg["grid_eval_users"], seed)
    grid = []
    for point in grid_points(cfg):
        started = time.monotonic()
        model = fit_als(grid_train, point, cfg, seed)
        fit_seconds = time.monotonic() - started
        res = evaluate_users(grid_val, model.item_ids, als_scorer(model), [k_sel], rel,
                             fallback=popularity_scores(stats, model.item_ids))  # fmt: skip
        grid.append({**dataclasses.asdict(point), "val_ndcg": _ndcg(res, k_sel),
                     "fit_seconds": round(fit_seconds, 1)})  # fmt: skip
        logger.info("Grille %s : NDCG@%d validation %.4f", point, k_sel, grid[-1]["val_ndcg"])
    grid_train.unpersist()
    best = {
        kind: max((g for g in grid if g["kind"] == kind), key=lambda g: g["val_ndcg"])
        for kind in KINDS
    }
    for kind, b in best.items():
        if _on_grid_edge(b, cfg):
            logger.warning("%s : meilleur point au bord de la grille (%s)", kind, b)

    # 2. Meilleur point de chaque variante réentraîné sur TOUT le train.
    points = {k: GridPoint(k, best[k]["rank"], best[k]["reg_param"]) for k in KINDS}
    models = {kind: fit_als(train, points[kind], cfg, seed) for kind in KINDS}
    item_ids = models["als_explicit"].item_ids
    if not np.array_equal(item_ids, models["als_implicit"].item_ids):
        raise RuntimeError("les deux ALS n'ont pas le même catalogue : comparaison faussée")
    popularity = popularity_scores(stats, item_ids)

    def run_eval(part: pd.DataFrame, rmse: bool = True) -> dict[str, dict[str, Any]]:
        return {
            "popularity": evaluate_users(part, item_ids, lambda i, s: popularity, ks, rel),
            "als_explicit": evaluate_users(
                part, item_ids, als_scorer(models["als_explicit"]), ks, rel,
                fallback=popularity,
                predict=als_predictor(models["als_explicit"], means) if rmse else None,
            ),
            "als_implicit": evaluate_users(
                part, item_ids, als_scorer(models["als_implicit"]), ks, rel, fallback=popularity,
            ),
        }  # fmt: skip

    def item_mean_rmse(part: pd.DataFrame) -> float | None:
        # Baseline de la RMSE : moyenne (lissée) de l'anime. Ce n'est PAS la popularité, qui
        # classe mais ne prédit pas de note.
        targets = part[part["masked"] & part["anime_id"].isin(item_ids)]
        return rmse_fn(targets["score"].to_numpy(float), means.reindex(targets["anime_id"]))

    # 3. Choix final sur la validation complète ; test évalué une seule fois.
    val_results = run_eval(val)
    final_kind = max(KINDS, key=lambda k: _ndcg(val_results[k], k_sel))
    test_results = run_eval(test)
    final = models[final_kind]
    rmse_test = {
        "item_mean": item_mean_rmse(test),
        "als_explicit": test_results["als_explicit"]["rmse"],
    }

    # 4. Régime d'usage réel : un nouvel utilisateur ne donne que quelques animes aimés, sans
    # note. Mêmes utilisateurs de test, mêmes cibles ; seul le signal transmis change.
    onboarding = {}
    for n in cfg["onboarding_n_liked"]:
        profile, excluded = onboarding_profile(test, n, rel, cfg["onboarding_default_score"], seed)
        onboarding[str(n)] = {
            "users": int(profile["user_id"].nunique()),
            "users_excluded": excluded,
            "models": run_eval(profile, rmse=False),
        }
        logger.info("Onboarding %d animes aimés : NDCG@%d %s", n, k_sel, {
            k: round(_ndcg(v, k_sel), 4) for k, v in onboarding[str(n)]["models"].items()
        })  # fmt: skip

    figures = resolve_path(settings, "reports") / "figures"
    plot_grid(grid, k_sel, figures / "reco_grid.png")
    plot_at_k(test_results, "ndcg", figures / "reco_ndcg_at_k.png")
    plot_at_k(test_results, "recall", figures / "reco_recall_at_k.png")
    plot_onboarding(onboarding, k_sel, figures / "reco_onboarding.png")

    run_id, created_at = str(uuid.uuid4()), datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    showcase = _showcase(settings, final, popularity, cfg["onboarding_default_score"])
    report = {
        "generated_at": created_at,
        "run_id": run_id,
        "data": {
            **json.loads(_prepare_stats(settings).read_text(encoding="utf-8")),
            "catalog_size": int(len(item_ids)),
            "train_global_mean": global_mean,
            "grid_eval_users": int(grid_val["user_id"].nunique()),
        },
        "protocol": {
            "relevant_min_score": rel,
            "selection_metric": f"ndcg@{k_sel} (validation)",
            "mask_fraction": cfg["mask_fraction"],
            "rmse_predictions_clipped_to": [1, 10],
        },
        "grid": grid,
        "selection": {k: {**b, "on_grid_edge": _on_grid_edge(b, cfg)} for k, b in best.items()},
        "final_model": final_kind,
        "val": val_results,
        "test": test_results,
        "rmse_test": rmse_test,
        "onboarding_test": onboarding,
        "showcase": showcase,
    }

    top_popular = item_ids[top_k_positions(popularity, np.array([], dtype=int), 500)]
    card = {
        "run_id": run_id,
        "created_at": created_at,
        "model_name": "reco",
        "model_type": final_kind,
        "params": {
            "rank": points[final_kind].rank,
            "reg_param": points[final_kind].reg_param,
            "max_iter": cfg["max_iter"],
            "implicit_alpha": cfg["implicit_alpha"],
            "implicit_neutral_score": cfg["implicit_neutral_score"],
            "grid_user_fraction": cfg["grid_user_fraction"],
            "grid_eval_users": cfg["grid_eval_users"],
        },
        "metrics": {"test": test_results[final_kind]},
        "relevant_min_score": rel,
        "onboarding_default_score": cfg["onboarding_default_score"],
        # Repli quand le fold-in est impossible (aucun anime connu, aucune préférence positive) :
        # les plus populaires, assez nombreux pour rester ≥ K une fois les animes vus retirés.
        "popularity_fallback": [int(a) for a in top_popular],
        # Cas de référence pour le backend (phase 5) : avec ces notes, son fold-in doit renvoyer
        # exactement ce top 10. Test de parité sans dépendre du paquet pipeline.
        "parity_check": {
            "anime_ids": showcase.get("liked_ids", []),
            "scores": [float(cfg["onboarding_default_score"])] * len(showcase.get("liked_ids", [])),
            "expected_top10": showcase.get("recommended_ids", []),
        },
        "data_fingerprint": data_fingerprint(settings, "reco"),
        "versions": {
            "pyspark": pyspark.__version__,
            "numpy": np.__version__,
            "git_sha": _git_sha(),
        },
    }
    # Artefact d'abord, rapport ensuite (écriture atomique) : un échec de sauvegarde ne laisse
    # jamais un rapport qui décrit un modèle absent.
    save_reco_artifact(final, card, resolve_path(settings, "models"))
    _write_json_atomic(resolve_path(settings, "reports") / "reco_metrics.json", report)
    train.unpersist()
    logger.info(
        "Modèle final : %s — NDCG@%d test %.4f (popularité %.4f)",
        final_kind,
        k_sel,
        test_results[final_kind]["at_k"][str(k_sel)]["ndcg"],
        test_results["popularity"]["at_k"][str(k_sel)]["ndcg"],
    )


# --- register (Postgres) -----------------------------------------------------------------------


def _build_register(_spark: SparkSession | None, settings: dict[str, Any]) -> None:
    card = verify_reco_artifact(resolve_path(settings, "models"))
    run = {f: card[f] for f in loader.MODEL_RUN_FIELDS}
    with loader.connect(loader.database_url()) as conn:
        loader.apply_schemas(conn)
        loader.insert_model_run(conn, run)


def _prepare_config(s: dict[str, Any]) -> dict[str, Any]:
    cfg = require_section(s, "reco")
    keys = ("min_user_ratings", "min_item_ratings", "val_fraction", "test_fraction",
            "mask_fraction")  # fmt: skip
    return {**{k: cfg[k] for k in keys}, "seed": s["project"]["seed"]}


def _fit_config(s: dict[str, Any]) -> dict[str, Any]:
    return {"reco": require_section(s, "reco"), "seed": s["project"]["seed"],
            "showcase": s.get("key_figures", {}).get("showcase_titles", [])}  # fmt: skip


STEP_DEFS = {
    "prepare": Step(
        "reco_prepare",
        inputs=lambda s: [_clean(s, "rating_complete")],
        outputs=lambda s: [_reco_dir(s) / "train", _reco_dir(s) / "holdout", _prepare_stats(s)],
        build=_build_prepare,
        config=_prepare_config,
        stamp_dir=stamp_dir,
    ),
    "fit": Step(
        "reco_fit",
        # clean/anime : lu pour les exemples (titres) et le cas de parité de la fiche.
        inputs=lambda s: [
            _reco_dir(s) / "train",
            _reco_dir(s) / "holdout",
            _prepare_stats(s),
            _clean(s, "anime"),
        ],  # fmt: skip
        outputs=lambda s: [
            resolve_path(s, "reports") / "reco_metrics.json",
            *reco_paths(resolve_path(s, "models")),
        ],
        build=_build_fit,
        config=_fit_config,
        stamp_dir=stamp_dir,
    ),
    "register": Step(
        "reco_register",
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
    # Spark seulement si prepare ou fit doit vraiment tourner (register n'en a pas besoin).
    needs_spark = any(
        name in steps and (force or not STEP_DEFS[name].is_up_to_date(settings))
        for name in ("prepare", "fit")
    )
    owns_session = needs_spark and spark is None
    if owns_session:
        spark = build_spark(settings, app_name="tsuzuku-reco")
    try:
        for name in STEPS:
            if name in steps:
                STEP_DEFS[name].run(spark, settings, force)
    finally:
        if owns_session:
            spark.stop()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Phase 4 : recommandation ALS.")
    parser.add_argument("--step", action="append", choices=STEPS, help="Étape(s), répétable.")
    parser.add_argument("--force", action="store_true", help="Refait même si à jour.")
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s | %(message)s"
    )
    run(load_settings(), steps=args.step or STEPS, force=args.force)


if __name__ == "__main__":
    main()
