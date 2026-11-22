"""Lancer une tâche d'ingestion hors d'Airflow (make covers, make covers-report).

Les DAG restent le chemin normal ; cette commande sert au premier remplissage et au dépannage.
"""

import argparse
import datetime as dt
import json
import logging

from tsuzuku_pipeline.config import load_settings
from tsuzuku_pipeline.ingestion import covers_report, jobs


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="tsuzuku-ingest")
    parser.add_argument(
        "task",
        choices=["covers", "covers-report"],
        help="covers : jaquettes des animes (AniList) ; covers-report : rapport de couverture",
    )
    parser.add_argument(
        "--include-small",
        action="store_true",
        help="covers : redemande aussi les petites images AniList (remise à niveau)",
    )
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    day = dt.datetime.now(dt.UTC).date()
    if args.task == "covers":
        print(
            json.dumps(
                jobs.anilist_covers(load_settings(), day, include_small=args.include_small),
                ensure_ascii=False,
            )
        )
    elif args.task == "covers-report":
        settings = load_settings()
        with jobs.connection() as conn:
            path = covers_report.write(conn, jobs.resolve_path(settings, "reports"))
        print(path)


if __name__ == "__main__":
    main()
