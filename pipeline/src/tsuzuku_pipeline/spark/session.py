"""Création de la SparkSession locale, configurée depuis settings.yaml."""

from typing import Any

from pyspark.sql import SparkSession

from tsuzuku_pipeline.config import require_section


def build_spark(settings: dict[str, Any], app_name: str = "tsuzuku") -> SparkSession:
    """SparkSession en mode local, sur tous les cœurs de la machine.

    - driver_memory : en mode local, le driver EST l'exécuteur ; c'est donc toute la RAM de Spark.
      Elle doit être fixée avant le démarrage de la JVM, d'où la config ici et pas plus tard.
    - shuffle_partitions : 200 par défaut, pensé pour un cluster ; en local ça crée des centaines
      de micro-tâches. On le règle à ~2-3x le nombre de cœurs.
    - fuseau UTC : rend les dates reproductibles quelle que soit la machine.
    """
    conf = require_section(settings, "spark")
    return (
        SparkSession.builder.appName(app_name)
        .master(conf.get("master", "local[*]"))
        .config("spark.driver.memory", conf["driver_memory"])
        .config("spark.sql.shuffle.partitions", str(conf.get("shuffle_partitions", 48)))
        .config("spark.sql.session.timeZone", "UTC")
        .config("spark.ui.showConsoleProgress", "false")
        .getOrCreate()
    )
