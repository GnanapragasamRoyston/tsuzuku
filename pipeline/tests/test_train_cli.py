"""Test de bout en bout de `make train` : mini couche clean → features → fit → model_runs."""

import json

import numpy as np
import pytest

from tsuzuku_pipeline import train_cli
from tsuzuku_pipeline.ml.drop.export import load_artifact
from tsuzuku_pipeline.ml.drop.train import prepare_x

pytestmark = pytest.mark.db

LIST_SCHEMA = "user_id int, anime_id int, score int, watching_status int, watched_episodes int"
ANIME_SCHEMA = (
    "anime_id int, genres array<string>, type string, episodes int, duration_min double,"
    " source string, start_year int, rating string, popularity int, studios array<string>"
)


@pytest.fixture
def project(spark, tmp_path, settings, pg, pg_url, monkeypatch):
    rng = np.random.default_rng(0)
    clean = tmp_path / "parquet" / "clean"
    genres = [["Action"], ["Drama"], ["Action", "Comedy"], ["Comedy"]]
    anime_rows = [
        (a, genres[a % 4], ["TV", "Movie"][a % 2], 12, 24.0, "Manga", 2000 + a, "PG-13",
         a * 10, [f"S{a % 3}"])
        for a in range(1, 21)
    ]  # fmt: skip
    spark.createDataFrame(anime_rows, ANIME_SCHEMA).write.parquet(str(clean / "anime"))
    spark.createDataFrame(
        [(1, "Currently Watching"), (2, "Completed"), (3, "On Hold"), (4, "Dropped"),
         (6, "Plan to Watch")],
        "status int, description string",
    ).write.parquet(str(clean / "watching_status"))  # fmt: skip
    rows = []
    for u in range(120):
        dropper = u % 3 == 0  # un tiers des utilisateurs lâche souvent : signal apprenable
        for a in rng.choice(range(1, 21), size=12, replace=False):
            status = 4 if rng.uniform() < (0.6 if dropper else 0.05) else 2
            rows.append((u, int(a), int(rng.integers(0, 11)), status, 3))
    spark.createDataFrame(rows, LIST_SCHEMA).write.parquet(str(clean / "animelist"))

    settings["paths"] = {
        "raw": str(tmp_path / "raw"),
        "parquet": str(tmp_path / "parquet"),
        "features": str(tmp_path / "features"),
        "models": str(tmp_path / "models"),
        "reports": str(tmp_path / "reports"),
    }
    (tmp_path / "reports").mkdir()
    settings["drop_model"] = {
        "sample_user_fraction": 1.0,
        "val_fraction": 0.2,
        "test_fraction": 0.2,
        "top_studios": 2,
        "logreg": {"C": [1.0], "max_iter": 300},
        "hgb": {"learning_rate": [0.1], "max_leaf_nodes": [7], "max_iter": 30},
        "calibration": "none",
        "permutation_rows": 500,
        "permutation_repeats": 2,
    }
    monkeypatch.setenv("DATABASE_URL", pg_url)
    return tmp_path, settings


def test_end_to_end_training(spark, project, pg):
    root, settings = project
    train_cli.run(settings, spark=spark)

    report = json.loads((root / "reports" / "drop_metrics.json").read_text(encoding="utf-8"))
    assert report["final_model"] in ("logreg", "hgb")
    assert set(report["test"]) == {"dummy", "logreg", "hgb"}
    final = report["test"][report["final_model"]]
    assert final["pr_auc"] > report["test"]["dummy"]["pr_auc"]  # le signal est appris
    splits = report["data"]["splits"]
    assert sum(s["users"] for s in splits.values()) == report["data"]["users"]

    for fig in ("roc.png", "pr.png", "calibration.png", "importance.png"):
        assert (root / "reports" / "figures" / fig).is_file()

    model, card = load_artifact(root / "models")
    assert card["run_id"] == report["run_id"]
    sample = json.loads((root / "features" / "drop_genres.json").read_text(encoding="utf-8"))
    assert card["genres"] == sample
    import pandas as pd

    df = pd.read_parquet(root / "features" / "drop_sample").head(20)
    proba = model.predict_proba(prepare_x(df, card["genres"]))[:, 1]
    assert np.all((proba >= 0) & (proba <= 1))

    runs = pg.execute("SELECT run_id::text, model_type FROM mart.model_runs").fetchall()
    assert runs == [(report["run_id"], report["final_model"])]


def test_rerun_without_changes_skips_training_and_spark(spark, project, pg):
    root, settings = project
    train_cli.run(settings, spark=spark)
    card = (root / "models" / "drop_model.json").read_text(encoding="utf-8")

    train_cli.run(settings, spark=None)  # aucun Spark : rien ne doit en avoir besoin
    assert (root / "models" / "drop_model.json").read_text(encoding="utf-8") == card
    assert pg.execute("SELECT count(*) FROM mart.model_runs").fetchone()[0] == 1


def test_changing_grid_retrains_without_recomputing_features(spark, project):
    root, settings = project
    train_cli.run(settings, steps=["features", "fit"], spark=spark)
    features_mark = (root / "features" / "drop_all" / "_SUCCESS").stat().st_mtime_ns
    card = json.loads((root / "models" / "drop_model.json").read_text(encoding="utf-8"))

    settings["drop_model"]["hgb"]["max_leaf_nodes"] = [15]
    train_cli.run(settings, steps=["features", "fit"], spark=None)
    new_card = json.loads((root / "models" / "drop_model.json").read_text(encoding="utf-8"))
    assert new_card["run_id"] != card["run_id"]
    assert (root / "features" / "drop_all" / "_SUCCESS").stat().st_mtime_ns == features_mark
