"""Création de la SparkSession locale, configurée depuis settings.yaml."""

from pathlib import Path
from typing import Any

from pyspark.sql import SparkSession

from tsuzuku_pipeline.config import REPO_ROOT, require_section

DEFAULT_LOCAL_DIR = "data/.spark-tmp"


def spark_conf(settings: dict[str, Any]) -> dict[str, str]:
    """Réglages Spark dérivés de settings.yaml (fonction pure : testable sans démarrer de JVM).

    - driver_memory : en mode local, le driver EST l'exécuteur ; c'est donc toute la RAM de Spark.
      Elle doit être fixée avant le démarrage de la JVM, d'où la config ici et pas plus tard.
    - shuffle_partitions : 200 par défaut, pensé pour un cluster ; en local ça crée des centaines
      de micro-tâches. On le règle à ~2-3x le nombre de cœurs.
    - local_dir : où Spark déverse sur disque ce qui ne tient pas en mémoire (tris, shuffles).
      Par défaut c'est /tmp, qui sous WSL est un tmpfs EN RAM (7,7 Go ici) : un gros job le
      remplit et échoue en « No space left on device » (vécu en phase 3). On le place sur le
      vrai disque, dans data/ (gitignoré).
    - fuseau UTC : rend les dates reproductibles quelle que soit la machine.
    """
    conf = require_section(settings, "spark")
    local_dir = Path(conf.get("local_dir", DEFAULT_LOCAL_DIR))
    if not local_dir.is_absolute():
        local_dir = REPO_ROOT / local_dir
    return {
        "spark.master": conf.get("master", "local[*]"),
        "spark.driver.memory": conf["driver_memory"],
        "spark.sql.shuffle.partitions": str(conf.get("shuffle_partitions", 48)),
        "spark.local.dir": str(local_dir),
        "spark.sql.session.timeZone": "UTC",
        "spark.ui.showConsoleProgress": "false",
    }


def build_spark(settings: dict[str, Any], app_name: str = "tsuzuku") -> SparkSession:
    """SparkSession en mode local, sur tous les cœurs de la machine (voir spark_conf)."""
    conf = spark_conf(settings)
    Path(conf["spark.local.dir"]).mkdir(parents=True, exist_ok=True)
    builder = SparkSession.builder.appName(app_name)
    for key, value in conf.items():
        builder = builder.config(key, value)
    return builder.getOrCreate()
