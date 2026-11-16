"""`make figures` : regroupe les chiffres clés du projet dans reports/key_figures.{json,md}.

But : avoir en un seul endroit, prêts à exporter ou à mettre en graphique (README, Power BI,
entretien), les chiffres de chaque phase. Ce module ne CALCULE ni n'ÉCRIT aucun chiffre lui-même :
il relit les rapports générés par le pipeline (et les marts), et chaque valeur garde sa source.
Règle du projet : aucun chiffre inventé (CLAUDE.md § 5).
"""

import argparse
import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from tsuzuku_pipeline.config import ConfigError, load_settings, resolve_path

logger = logging.getLogger("tsuzuku_pipeline.figures")

REPORT_FILES = {
    "data_quality": "data_quality.json",
    "marts_summary": "marts_summary.json",
    "drop_metrics": "drop_metrics.json",
    "reco_metrics": "reco_metrics.json",
}


def _load_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        logger.warning("%s absent : section ignorée", path.name)
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _data_section(dq: dict[str, Any]) -> dict[str, Any]:
    t, f = dq["tables"], dq["filters"]
    return {
        "interactions_raw": t["animelist"]["rows"],
        "interactions_clean": f["animelist"]["rows_after"],
        "users": t["animelist"]["distinct_users"],
        "anime_raw": f["anime"]["rows_before"],
        "anime_clean": f["anime"]["rows_after"],
        "adult_anime": t["anime"]["adult_total"],
        "adult_anime_by_genre_only": t["anime"]["adult_by_genre_only"],
        "adult_interactions_removed": f["animelist"]["removed_adult"],
        "unknown_status_rows_removed": f["animelist"]["removed_unknown_status"],
        "duplicate_rows_removed": f["animelist"]["removed_duplicates"],
        "ratings_raw": t["rating_complete"]["rows"],
        "ratings_clean": f["rating_complete"]["rows_after"],
        "status_counts": [
            {"status": k, "rows": v} for k, v in t["animelist"]["status_counts"].items()
        ],
    }


def _marts_section(
    summary: dict[str, Any], marts_dir: Path, anime_path: Path, showcase: list[str]
) -> dict[str, Any]:
    section: dict[str, Any] = {
        "drop_curve_rows": summary["drop_curve"]["rows"],
        "anime_with_drop_curve": summary["drop_curve"]["anime"],
        "anime_with_critical_episode": summary["critical_episode"]["anime"],
        "anime_with_point_of_no_return": summary["critical_episode"]["with_point_of_no_return"],
        "genres_published": summary["retention_by_genre"]["rows"],
        "studios_published": summary["retention_by_studio"]["rows"],
    }
    genre_path = marts_dir / "retention_by_genre"
    if genre_path.exists():
        genres = pd.read_parquet(genre_path).sort_values("drop_rate", ascending=False)
        section["genres_by_drop_rate"] = genres[
            ["genre", "nb_anime", "drop_rate", "completion_rate", "median_drop_progress"]
        ].to_dict("records")
    crit_path = marts_dir / "critical_episode"
    if showcase and crit_path.exists() and anime_path.exists():
        # Exemples parlants, retrouvés par TITRE exact dans les données (jamais par un id deviné).
        crit = pd.read_parquet(crit_path)
        names = pd.read_parquet(anime_path, columns=["anime_id", "name", "episodes"])
        merged = crit.merge(names, on="anime_id").set_index("name")
        section["showcase"] = [
            {
                "title": title,
                # _int : pandas passe en float une colonne entière qui contient des NaN (37 → 37.0).
                "episodes": _int(merged.at[title, "episodes"]),
                "critical_episode": _int(merged.at[title, "critical_episode"]),
                "point_of_no_return": _int(merged.at[title, "point_of_no_return"]),
                "initial_drop_risk": _py(merged.at[title, "initial_drop_risk"]),
                "drop_rate": _py(merged.at[title, "drop_rate"]),
            }
            for title in showcase
            if title in merged.index
        ]
        missing = [t for t in showcase if t not in merged.index]
        if missing:
            logger.warning("Titres sans épisode critique publié : %s", ", ".join(missing))
    return section


def _py(value: Any) -> Any:
    """numpy/pandas → types Python (JSON) ; NaN → None."""
    if value is None or (isinstance(value, float) and value != value) or pd.isna(value):
        return None
    return value.item() if hasattr(value, "item") else value


def _int(value: Any) -> int | None:
    value = _py(value)
    return None if value is None else int(value)


def _drop_model_section(dm: dict[str, Any]) -> dict[str, Any]:
    keys = ("pr_auc", "roc_auc", "f1", "precision", "recall", "brier", "ece", "threshold")
    return {
        "run_id": dm["run_id"],
        "final_model": dm["final_model"],
        "calibration": dm["calibration"],
        "sample": {"rows": dm["data"]["rows"], "users": dm["data"]["users"]},
        "splits": [{"split": k, **v} for k, v in dm["data"]["splits"].items()],
        "models_on_test": [{"model": k, **{m: v[m] for m in keys}} for k, v in dm["test"].items()],
        "confusion_final_test": dm["test"][dm["final_model"]]["confusion"],
        "top_features": dm["permutation_importance_test"][:10],
        "calibration_bins_test": dm["calibration_bins_test"],
    }


def _reco_section(rm: dict[str, Any]) -> dict[str, Any]:
    d = rm["data"]
    return {
        "run_id": rm["run_id"],
        "final_model": rm["final_model"],
        "ratings_before_filter": d["rows_before"],
        "ratings_after_filter": d["rows_after"],
        "users_after_filter": d["users_after"],
        "anime_after_filter": d["anime_after"],
        "catalog_size": d["catalog_size"],
        "relevant_min_score": rm["protocol"]["relevant_min_score"],
        "splits": [{"split": k, **v} for k, v in d["splits"].items()],
        # Format « long » (une ligne par modèle et par K) : directement traçable.
        "models_on_test": [
            {"model": model, "k": int(k), **metrics}
            for model, res in rm["test"].items()
            for k, metrics in res["at_k"].items()
        ],
        "rmse_test": [{"model": m, "rmse": v} for m, v in rm.get("rmse_test", {}).items()],
        # Régime onboarding : NDCG@k selon le nombre d'animes aimés donnés (format long).
        "onboarding_test": [
            {
                "n_liked": int(n),
                "users": block["users"],
                "model": model,
                "k": int(k),
                "ndcg": metrics["ndcg"],
                "recall": metrics["recall"],
            }
            for n, block in rm.get("onboarding_test", {}).items()
            for model, res in block["models"].items()
            for k, metrics in res["at_k"].items()
        ],  # fmt: skip
        "grid": rm["grid"],
        "showcase": rm.get("showcase", {}),
    }


def collect(settings: dict[str, Any]) -> dict[str, Any]:
    reports = resolve_path(settings, "reports")
    loaded = {name: _load_json(reports / f) for name, f in REPORT_FILES.items()}
    showcase = settings.get("key_figures", {}).get("showcase_titles", [])
    bad = [t for t in showcase if not isinstance(t, str)]
    if bad:
        # Piège YAML vécu : un titre contenant « : » sans guillemets devient un dictionnaire.
        raise ConfigError(
            f"key_figures.showcase_titles : titres non textuels {bad} — mets-les entre guillemets"
        )

    figures: dict[str, Any] = {
        "generated_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "sources": {
            name: {"file": f"reports/{REPORT_FILES[name]}", "generated_at": doc["generated_at"]}
            for name, doc in loaded.items()
            if doc is not None
        },
    }
    if loaded["data_quality"]:
        figures["data"] = _data_section(loaded["data_quality"])
    if loaded["marts_summary"]:
        figures["marts"] = _marts_section(
            loaded["marts_summary"],
            resolve_path(settings, "marts"),
            resolve_path(settings, "parquet") / "clean" / "anime",
            showcase,
        )
    if loaded["drop_metrics"]:
        figures["drop_model"] = _drop_model_section(loaded["drop_metrics"])
    if loaded["reco_metrics"]:
        figures["reco"] = _reco_section(loaded["reco_metrics"])
    figures["exploration"] = [
        {"file": f"reports/{p.name}", **json.loads(p.read_text(encoding="utf-8"))}
        for p in sorted(reports.glob("exploration_*.json"))
    ]
    return figures


def _fmt(v: Any) -> str:
    if isinstance(v, bool) or v is None:
        return "—" if v is None else str(v)
    if isinstance(v, int):
        return f"{v:,}".replace(",", " ")
    if isinstance(v, float):
        return f"{v:.4f}".rstrip("0").rstrip(".") if abs(v) < 1000 else f"{v:,.0f}"
    return str(v)


def _table(records: list[dict[str, Any]]) -> list[str]:
    if not records:
        return ["_(vide)_"]
    cols = list(records[0])
    lines = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    lines += ["| " + " | ".join(_fmt(r.get(c)) for c in cols) + " |" for r in records]
    return lines


def render_markdown(fig: dict[str, Any]) -> str:
    """Vue lisible de key_figures.json (mêmes valeurs, aucune ajoutée)."""
    out = ["# Chiffres clés — Tsuzuku", "", f"Généré le {fig['generated_at']} par `make figures`.",
           "Sources :"]  # fmt: skip
    out += [f"- `{s['file']}` (généré le {s['generated_at']})" for s in fig["sources"].values()]
    for key, title in (("data", "Données (phase 1)"), ("marts", "Marts (phase 2)"),
                       ("drop_model", "Modèle de drop (phase 3)"),
                       ("reco", "Recommandation ALS (phase 4)")):  # fmt: skip
        if key not in fig:
            continue
        out += ["", f"## {title}", ""]
        scalars = {k: v for k, v in fig[key].items() if not isinstance(v, (list, dict))}
        out += _table([{"indicateur": k, "valeur": v} for k, v in scalars.items()])
        for k, v in fig[key].items():
            if isinstance(v, list):
                out += ["", f"### {k}", "", *_table(v)]
            elif isinstance(v, dict):
                out += ["", f"### {k}", "", *_table([v])]
    if fig["exploration"]:
        out += ["", "## Mesures d'exploration (ponctuelles)", ""]
        for doc in fig["exploration"]:
            for m in doc["measurements"]:
                out += [f"- **{m['id']}** (phase {m['phase']}) — {m['source']} — `{doc['file']}`"]
    return "\n".join(out) + "\n"


def run(settings: dict[str, Any]) -> dict[str, Any]:
    figures = collect(settings)
    reports = resolve_path(settings, "reports")
    (reports / "key_figures.json").write_text(
        json.dumps(figures, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    (reports / "key_figures.md").write_text(render_markdown(figures), encoding="utf-8")
    logger.info("Chiffres clés écrits dans %s", reports / "key_figures.json")
    return figures


def main(argv: list[str] | None = None) -> None:
    argparse.ArgumentParser(description="Regroupe les chiffres clés générés.").parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s | %(message)s")
    run(load_settings())


if __name__ == "__main__":
    main()
