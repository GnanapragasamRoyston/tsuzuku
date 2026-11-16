"""Test de bout en bout de `make reco` : mini rating_complete → prepare → fit → model_runs."""

import json

import numpy as np
import pandas as pd
import pytest

from tsuzuku_pipeline import reco_cli
from tsuzuku_pipeline.ml.reco.export import load_reco_model
from tsuzuku_pipeline.ml.reco.fold_in import fold_in, recommend


@pytest.fixture
def project_files(spark, tmp_path, settings):
    """Mini projet SANS Postgres (étapes prepare et fit)."""
    rng = np.random.default_rng(0)
    clean = tmp_path / "parquet" / "clean"
    # Deux groupes de goûts : les utilisateurs pairs aiment les animes 1-20, les impairs 21-40.
    # Un signal que l'ALS peut apprendre et que la popularité (équilibrée) ne capte pas.
    rows = []
    for u in range(240):
        own = range(1, 21) if u % 2 == 0 else range(21, 41)
        other = range(21, 41) if u % 2 == 0 else range(1, 21)
        for a in rng.choice(list(own), size=12, replace=False):
            rows.append((u, int(a), int(rng.integers(8, 11))))
        for a in rng.choice(list(other), size=3, replace=False):
            rows.append((u, int(a), int(rng.integers(2, 6))))
    spark.createDataFrame(rows, "user_id int, anime_id int, score int").write.parquet(
        str(clean / "rating_complete")
    )
    anime = [(a, f"Anime {a}") for a in range(1, 41)]
    spark.createDataFrame(anime, "anime_id int, name string").write.parquet(str(clean / "anime"))

    settings["paths"] = {
        "raw": str(tmp_path / "raw"),
        "parquet": str(tmp_path / "parquet"),
        "features": str(tmp_path / "features"),
        "models": str(tmp_path / "models"),
        "reports": str(tmp_path / "reports"),
    }
    (tmp_path / "reports").mkdir()
    (tmp_path / "features").mkdir()
    settings["reco"] = {
        "min_user_ratings": 5,
        "min_item_ratings": 5,
        "val_fraction": 0.2,
        "test_fraction": 0.2,
        "mask_fraction": 0.3,
        "relevant_min_score": 8,
        "onboarding_default_score": 8,
        "implicit_neutral_score": 5,
        "implicit_alpha": 1.0,
        "baseline_shrinkage": 10,
        "grid_user_fraction": 1.0,
        "grid_eval_users": 1000,
        "ranks": [2, 4],
        "reg_params": [0.1],
        "max_iter": 8,
        "num_blocks": 2,
        "k_values": [5, 10],
        "selection_k": 5,
        "onboarding_n_liked": [1, 3],
    }
    settings["key_figures"] = {"showcase_titles": ["Anime 1", "Anime 2", "Anime 3"]}
    return tmp_path, settings


@pytest.fixture
def project(project_files, pg, pg_url, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", pg_url)
    return project_files


@pytest.mark.db
def test_end_to_end_reco(spark, project, pg):
    root, settings = project
    reco_cli.run(settings, spark=spark)

    report = json.loads((root / "reports" / "reco_metrics.json").read_text(encoding="utf-8"))
    assert report["final_model"] in ("als_explicit", "als_implicit")
    assert set(report["test"]) == {"popularity", "als_explicit", "als_implicit"}
    assert len(report["grid"]) == 4
    # Les utilisateurs val/test ne sont pas dans le train de l'ALS.
    splits = report["data"]["splits"]
    assert splits["train"]["masked"] == 0 and splits["test"]["masked"] > 0
    final = report["test"][report["final_model"]]["at_k"]["5"]["ndcg"]
    assert final > report["test"]["popularity"]["at_k"]["5"]["ndcg"]  # le signal est appris
    # RMSE : seulement pour les modèles qui prédisent une note ; baseline = moyenne de l'anime.
    assert report["test"]["als_implicit"]["rmse"] is None
    assert report["test"]["popularity"]["rmse"] is None
    assert set(report["rmse_test"]) == {"item_mean", "als_explicit"}
    # Régime onboarding : mêmes cibles, signal réduit à n animes aimés.
    assert set(report["onboarding_test"]) == {"1", "3"}
    assert report["onboarding_test"]["3"]["users"] > 0
    assert set(report["selection"]["als_explicit"]) >= {"rank", "reg_param", "on_grid_edge"}
    # Profil « a aimé Anime 1-3 » (groupe pair) : ses recos viennent du même groupe.
    recommended = report["showcase"]["recommended"]
    assert sum(int(n.split()[1]) <= 20 for n in recommended[:5]) >= 4

    for fig in ("reco_grid.png", "reco_ndcg_at_k.png", "reco_recall_at_k.png",
                "reco_onboarding.png"):  # fmt: skip
        assert (root / "reports" / "figures" / fig).is_file()

    model, card = load_reco_model(root / "models")
    assert card["run_id"] == report["run_id"]
    assert card["model_type"] == report["final_model"]
    assert card["schema_version"] == 1 and card["n_items"] == len(model.item_ids)
    assert "numpy" in card["versions"] and "git_sha" in card["versions"]
    # Cas de parité : le modèle rechargé redonne exactement le top 10 enregistré.
    check = card["parity_check"]
    vec = fold_in(model, np.array(check["anime_ids"]), np.array(check["scores"]))
    top = recommend(model, vec, exclude=check["anime_ids"], k=10)
    assert top.tolist() == check["expected_top10"]

    runs = pg.execute("SELECT run_id::text, model_name FROM mart.model_runs").fetchall()
    assert runs == [(report["run_id"], "reco")]


def test_holdout_users_are_disjoint_from_train(spark, project_files):
    # Test anti-fuite : ne dépend pas de Postgres, il tourne partout.
    root, settings = project_files
    reco_cli.run(settings, steps=["prepare"], spark=spark)
    train = pd.read_parquet(root / "features" / "reco" / "train")
    holdout = pd.read_parquet(root / "features" / "reco" / "holdout")
    assert not set(train["user_id"]) & set(holdout["user_id"])
    assert set(holdout["split"]) == {"val", "test"}


@pytest.mark.db
def test_rerun_without_changes_skips_everything(spark, project, pg):
    root, settings = project
    reco_cli.run(settings, spark=spark)
    card = (root / "models" / "reco_model.json").read_text(encoding="utf-8")
    reco_cli.run(settings, spark=None)  # tout est à jour : Spark ne doit pas être nécessaire
    assert (root / "models" / "reco_model.json").read_text(encoding="utf-8") == card
    assert pg.execute("SELECT count(*) FROM mart.model_runs").fetchone()[0] == 1
