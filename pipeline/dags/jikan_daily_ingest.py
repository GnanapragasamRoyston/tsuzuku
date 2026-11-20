"""Ingestion quotidienne Jikan (SPEC § 9) : saison en cours + watchlist → catalog.media_daily_stats.

collect → fetch_stats → load → quality_check. Chaque tâche lit/écrit des fichiers bruts datés
(data/raw/jikan/<date>/) : une tâche se relance seule, et relancer la même date ne crée aucun
doublon (upsert sur la date et l'œuvre). Un anime en échec est noté et garde score et membres ;
au-delà de `ingestion.jikan.max_failure_share`, fetch_stats échoue. Le code métier vit dans
tsuzuku_pipeline.ingestion (testé sans Airflow) ; ce fichier ne fait qu'enchaîner les tâches.
"""

import datetime as dt

import pendulum
from airflow.decorators import dag, task
from airflow.timetables.trigger import CronTriggerTimetable


def _day(logical_date: pendulum.DateTime) -> dt.date:
    # CronTriggerTimetable : la date logique EST l'heure de déclenchement (06:00 du jour pour un
    # run planifié, l'instant du clic pour un run manuel). Avec le planning cron « classique »,
    # un run manuel lancé avant 06:00 aurait été daté de la veille et aurait écrasé son snapshot.
    return logical_date.in_timezone("UTC").date()


@dag(
    dag_id="jikan_daily_ingest",
    schedule=CronTriggerTimetable("0 6 * * *", timezone="UTC"),  # tous les jours à 06:00 UTC
    start_date=pendulum.datetime(2026, 11, 1, tz="UTC"),
    catchup=False,  # pas de rattrapage : Jikan ne donne que l'état ACTUEL, pas l'historique
    max_active_runs=1,
    default_args={"retries": 2, "retry_delay": dt.timedelta(minutes=10)},
    tags=["tsuzuku", "ingestion"],
    doc_md=__doc__,
)
def jikan_daily_ingest() -> None:
    from tsuzuku_pipeline.config import load_settings
    from tsuzuku_pipeline.ingestion import jobs

    @task
    def collect(logical_date=None) -> int:
        return jobs.jikan_collect(load_settings(), _day(logical_date))

    @task
    def fetch_stats(logical_date=None) -> dict:
        return jobs.jikan_fetch_stats(load_settings(), _day(logical_date))

    @task
    def load(logical_date=None) -> dict:
        return jobs.jikan_load(load_settings(), _day(logical_date))

    @task(retries=0)  # un contrôle qualité en échec ne se corrige pas en réessayant
    def quality_check(logical_date=None) -> dict:
        report = jobs.jikan_quality(load_settings(), _day(logical_date))
        return {k: report[k] for k in ("targets", "stats_fetched", "rows_for_day", "ok")}

    collect() >> fetch_stats() >> load() >> quality_check()


jikan_daily_ingest()
