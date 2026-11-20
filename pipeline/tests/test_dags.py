"""Les DAG se chargent sans erreur et ont la forme attendue.

Airflow n'est pas installé dans l'environnement du pipeline (dépendances lourdes, contraintes de
versions) : ce test est sauté ici et tourne dans l'image Airflow (make airflow-test, CI).
"""

import pytest

pytest.importorskip("airflow")

from airflow.configuration import conf  # noqa: E402
from airflow.models import DagBag  # noqa: E402

# Dossier des DAG configuré dans Airflow (dans l'image : /opt/airflow/dags, où ils sont montés).
DAGS_DIR = conf.get("core", "dags_folder")
EXPECTED = {"jikan_daily_ingest", "anilist_catalog_sync"}


@pytest.fixture(scope="module")
def dagbag():
    # read_dags_from_db=False : on veut les FICHIERS, pas une version sérialisée en base (une
    # base déjà remplie ferait passer le test même si les fichiers étaient introuvables).
    return DagBag(dag_folder=DAGS_DIR, include_examples=False, read_dags_from_db=False)


def test_no_import_errors_and_both_dags_found(dagbag):
    assert dagbag.import_errors == {}
    assert set(dagbag.dag_ids) == EXPECTED


@pytest.mark.parametrize(("dag_id", "tasks", "schedule"), [
    ("jikan_daily_ingest", ["collect", "fetch_stats", "load", "quality_check"], "0 6 * * *"),
    ("anilist_catalog_sync", ["fetch_pages", "load", "quality_check"], "0 5 * * 1"),
])  # fmt: skip
def test_dag_shape(dagbag, dag_id, tasks, schedule):
    from airflow.timetables.trigger import CronTriggerTimetable

    dag = dagbag.get_dag(dag_id)
    assert dag is not None and dag.catchup is False and dag.max_active_runs == 1
    # Date logique = heure de déclenchement (un run manuel n'est jamais daté de la veille).
    assert isinstance(dag.timetable, CronTriggerTimetable)
    assert dag.timetable.summary == schedule
    # Chaîne linéaire, dans l'ordre : chaque tâche dépend de la précédente.
    assert [t.task_id for t in dag.topological_sort()] == tasks
    for upstream, downstream in zip(tasks, tasks[1:], strict=False):
        assert downstream in dag.get_task(upstream).downstream_task_ids
    assert dag.get_task("quality_check").retries == 0
