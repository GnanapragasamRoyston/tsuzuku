"""L'image Airflow n'a pas PySpark : le code d'ingestion ne doit jamais l'importer, même
indirectement (sinon les DAG plantent à l'import dans le conteneur)."""

import subprocess
import sys

MODULES = [
    "tsuzuku_pipeline.ingestion.jobs",
    "tsuzuku_pipeline.ingestion.catalog_loader",
    "tsuzuku_pipeline.db.loader",
    "tsuzuku_pipeline.config",
]


def test_ingestion_does_not_import_pyspark():
    # Sous-processus : dans la suite de tests, pyspark est déjà chargé par d'autres tests.
    code = (
        "import sys\n"
        + "".join(f"import {m}\n" for m in MODULES)
        + "bad = sorted(m for m in sys.modules if m.split('.')[0] == 'pyspark')\n"
        + "print(','.join(bad))\n"
    )
    # Code fixe, écrit ci-dessus : aucune entrée extérieure.
    out = subprocess.run(  # noqa: S603
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    )
    assert out.stdout.strip() == "", f"pyspark importé : {out.stdout.strip()[:200]}"
