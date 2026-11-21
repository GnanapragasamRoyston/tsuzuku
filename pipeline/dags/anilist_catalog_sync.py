"""Synchronisation hebdomadaire du catalogue manga / manhwa / manhua depuis AniList (SPEC § 9).

fetch_pages → load → quality_check → anime_covers.

Les 5 000 titres les plus populaires (100 pages de 50, sous la limite de débit lue dans les
en-têtes d'AniList ; romans exclus) sont upsertés dans catalog.media (clé : anilist_id), avec
genres et tags. Aucune œuvre n'est supprimée ; un titre sorti du top perd son rang.
anime_covers (phase 8) remplit les couvertures manquantes des animes par leur idMal.
Le recalcul des embeddings des nouvelles œuvres s'ajoutera ici en phase 10.
"""

import datetime as dt

import pendulum
from airflow.decorators import dag, task
from airflow.timetables.trigger import CronTriggerTimetable


@dag(
    dag_id="anilist_catalog_sync",
    # Date logique = heure de déclenchement (voir jikan_daily_ingest) : un run manuel est daté du
    # jour où il tourne, pas du lundi précédent.
    schedule=CronTriggerTimetable("0 5 * * 1", timezone="UTC"),  # le lundi à 05:00 UTC
    start_date=pendulum.datetime(2026, 11, 1, tz="UTC"),
    catchup=False,
    max_active_runs=1,
    default_args={"retries": 1, "retry_delay": dt.timedelta(minutes=15)},
    tags=["tsuzuku", "ingestion"],
    doc_md=__doc__,
)
def anilist_catalog_sync() -> None:
    from tsuzuku_pipeline.config import load_settings
    from tsuzuku_pipeline.ingestion import jobs

    def day(logical_date: pendulum.DateTime) -> dt.date:
        return logical_date.in_timezone("UTC").date()

    @task
    def fetch_pages(logical_date=None) -> dict:
        return jobs.anilist_fetch(load_settings(), day(logical_date))

    @task
    def load(logical_date=None) -> dict:
        return jobs.anilist_load(load_settings(), day(logical_date))

    @task(retries=0)
    def quality_check(logical_date=None) -> dict:
        report = jobs.anilist_quality(load_settings(), day(logical_date))
        return {k: report[k] for k in ("pages", "fetched", "catalog_by_kind", "ok")}

    @task
    def anime_covers(logical_date=None) -> dict:
        # Après le catalogue et en série, jamais en parallèle : deux tâches AniList simultanées
        # doubleraient le débit et dépasseraient la limite de 30 requêtes par minute.
        return jobs.anilist_covers(load_settings(), day(logical_date))

    fetch_pages() >> load() >> quality_check() >> anime_covers()


anilist_catalog_sync()
