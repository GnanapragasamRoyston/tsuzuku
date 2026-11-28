"""Lancer une tâche d'ingestion hors d'Airflow.

- `covers`, `covers-report` : make covers, make covers-report (remplissage, dépannage) ;
- `anime-tags` : make anime-tags, tags AniList des animes du mart (ponctuel, phase 13 : les
  animes du mart viennent tous du dataset 2020, aucun nouveau n'y entre chaque semaine) ;
- `jikan-daily`, `anilist-weekly` : production (Cloud Run Job lancé par Cloud Scheduler, ADR 014),
  mêmes tâches et même ordre que les DAG Airflow, qui restent l'orchestrateur de dev et de démo.
"""

import argparse
import datetime as dt
import json
import logging

from tsuzuku_pipeline.config import load_settings
from tsuzuku_pipeline.ingestion import covers_report, jobs

CHAINS = {
    "jikan-daily": (
        ("collect", jobs.jikan_collect),
        ("fetch_stats", jobs.jikan_fetch_stats),
        ("load", jobs.jikan_load),
        ("quality_check", jobs.jikan_quality),
    ),
    "anilist-weekly": (
        ("fetch_pages", jobs.anilist_fetch),
        ("load", jobs.anilist_load),
        ("quality_check", jobs.anilist_quality),
        ("anime_covers", jobs.anilist_covers),
    ),
}


def run_chain(task: str, settings: dict, day: dt.date) -> None:
    """Une étape en échec lève et arrête la chaîne (code de sortie ≠ 0, le job est marqué en
    échec), comme une tâche en échec arrête le DAG. Les rapports partent dans les journaux."""
    for name, step in CHAINS[task]:
        result = step(settings, day)
        print(json.dumps({"task": task, "step": name, "result": result}, ensure_ascii=False,
                         default=str), flush=True)  # fmt: skip


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="tsuzuku-ingest")
    parser.add_argument(
        "task",
        choices=["covers", "covers-report", "anime-tags", *CHAINS],
        help="covers, covers-report, anime-tags (ponctuel) ; "
        "jikan-daily, anilist-weekly (production)",
    )
    parser.add_argument(
        "--include-small",
        action="store_true",
        help="covers : redemande aussi les petites images AniList (remise à niveau)",
    )
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    day = dt.datetime.now(dt.UTC).date()
    if args.task in CHAINS:
        run_chain(args.task, load_settings(), day)
    elif args.task == "covers":
        print(
            json.dumps(
                jobs.anilist_covers(load_settings(), day, include_small=args.include_small),
                ensure_ascii=False,
            )
        )
    elif args.task == "anime-tags":
        print(json.dumps(jobs.anilist_anime_tags(load_settings(), day), ensure_ascii=False))
    elif args.task == "covers-report":
        settings = load_settings()
        with jobs.connection() as conn:
            path = covers_report.write(conn, jobs.resolve_path(settings, "reports"))
        print(path)


if __name__ == "__main__":
    main()
