"""`make figures` : chaque chiffre vient d'un fichier généré, rien n'est inventé."""

import json

import pandas as pd

from tsuzuku_pipeline import key_figures

DQ = {
    "generated_at": "2026-11-16T10:00:00Z",
    "tables": {
        "anime": {"adult_total": 3, "adult_by_genre_only": 1},
        "animelist": {
            "rows": 100,
            "distinct_users": 7,
            "status_counts": {"Completed": 60, "Dropped": 10},
        },
        "rating_complete": {"rows": 50},
    },
    "filters": {
        "anime": {"rows_before": 20, "rows_after": 17},
        "animelist": {
            "rows_after": 90,
            "removed_adult": 8,
            "removed_unknown_status": 1,
            "removed_duplicates": 1,
        },
        "rating_complete": {"rows_after": 45},
    },
}
MS = {
    "generated_at": "2026-11-16T11:00:00Z",
    "drop_curve": {"rows": 40, "anime": 9},
    "critical_episode": {"anime": 2, "with_point_of_no_return": 1},
    "retention_by_genre": {"rows": 2},
    "retention_by_studio": {"rows": 1},
}
DM = {
    "generated_at": "2026-11-16T12:00:00Z",
    "run_id": "r1",
    "final_model": "hgb",
    "calibration": "none",
    "data": {
        "rows": 30,
        "users": 5,
        "splits": {"train": {"rows": 20, "users": 3, "prevalence": 0.1}},
    },  # fmt: skip
    "test": {
        m: {
            "pr_auc": 0.4,
            "roc_auc": 0.9,
            "f1": 0.4,
            "precision": 0.4,
            "recall": 0.5,
            "brier": 0.04,
            "ece": 0.005,
            "threshold": 0.24,
            "confusion": {"tn": 1, "fp": 2, "fn": 3, "tp": 4},
        }
        for m in ("dummy", "hgb")
    },  # fmt: skip
    "permutation_importance_test": [
        {"feature": f"f{i}", "importance": 0.1, "std": 0.0} for i in range(12)
    ],  # fmt: skip
    "calibration_bins_test": [{"mean_pred": 0.1, "observed": 0.1, "n": 3}],
}


def _project(tmp_path, settings, with_drop=True):
    reports = tmp_path / "reports"
    reports.mkdir()
    (reports / "data_quality.json").write_text(json.dumps(DQ))
    (reports / "marts_summary.json").write_text(json.dumps(MS))
    if with_drop:
        (reports / "drop_metrics.json").write_text(json.dumps(DM))
    (reports / "exploration_2026-11-16.json").write_text(
        json.dumps({"measurements": [{"id": "x", "phase": 2, "source": "s", "values": {}}]})
    )
    marts = tmp_path / "marts"
    (marts / "retention_by_genre").mkdir(parents=True)
    pd.DataFrame(
        {"genre": ["Action", "Drama"], "nb_anime": [5, 6], "drop_rate": [0.05, 0.08],
         "completion_rate": [0.8, 0.7], "median_drop_progress": [0.2, 0.3]}
    ).to_parquet(marts / "retention_by_genre" / "part.parquet")  # fmt: skip
    (marts / "critical_episode").mkdir()
    pd.DataFrame(
        {"anime_id": [1, 2], "critical_episode": [25, 1], "point_of_no_return": [26, None],
         "initial_drop_risk": [0.03, 0.1], "drop_rate": [0.04, 0.2]}
    ).to_parquet(marts / "critical_episode" / "part.parquet")  # fmt: skip
    anime = tmp_path / "parquet" / "clean" / "anime"
    anime.mkdir(parents=True)
    pd.DataFrame({"anime_id": [1, 2], "name": ["Death Note", "Autre"], "episodes": [37, 12]}
                 ).to_parquet(anime / "part.parquet")  # fmt: skip
    settings["paths"] = {"reports": str(reports), "marts": str(marts),
                         "parquet": str(tmp_path / "parquet")}  # fmt: skip
    settings["key_figures"] = {"showcase_titles": ["Death Note", "Titre absent"]}
    return reports


def test_figures_are_copied_from_reports_with_sources(tmp_path, settings):
    reports = _project(tmp_path, settings)
    fig = key_figures.run(settings)

    assert fig["data"]["interactions_raw"] == 100
    assert fig["data"]["interactions_clean"] == 90
    assert fig["marts"]["anime_with_critical_episode"] == 2
    assert [g["genre"] for g in fig["marts"]["genres_by_drop_rate"]] == ["Drama", "Action"]
    assert fig["marts"]["showcase"] == [
        {"title": "Death Note", "episodes": 37, "critical_episode": 25, "point_of_no_return": 26,
         "initial_drop_risk": 0.03, "drop_rate": 0.04}
    ]  # fmt: skip
    assert fig["drop_model"]["final_model"] == "hgb"
    assert len(fig["drop_model"]["top_features"]) == 10
    assert fig["sources"]["drop_metrics"]["generated_at"] == DM["generated_at"]
    assert fig["exploration"][0]["file"] == "reports/exploration_2026-11-16.json"

    on_disk = json.loads((reports / "key_figures.json").read_text(encoding="utf-8"))
    assert on_disk == json.loads(json.dumps(fig))
    md = (reports / "key_figures.md").read_text(encoding="utf-8")
    assert "Death Note" in md and "Modèle de drop" in md


def test_unquoted_yaml_title_gives_clear_error(tmp_path, settings):
    import pytest
    import yaml

    from tsuzuku_pipeline.config import ConfigError

    _project(tmp_path, settings)
    # Ce que YAML produit pour un titre non entre guillemets contenant « : ».
    settings["key_figures"] = yaml.safe_load("showcase_titles:\n  - Fullmetal Alchemist: B\n")
    with pytest.raises(ConfigError, match="guillemets"):
        key_figures.run(settings)


def test_real_settings_showcase_titles_are_strings():
    from tsuzuku_pipeline.config import load_settings

    titles = load_settings()["key_figures"]["showcase_titles"]
    assert titles and all(isinstance(t, str) for t in titles)


def test_missing_phase_report_is_skipped_not_invented(tmp_path, settings):
    _project(tmp_path, settings, with_drop=False)
    fig = key_figures.run(settings)
    assert "drop_model" not in fig
    assert "drop_metrics" not in fig["sources"]
