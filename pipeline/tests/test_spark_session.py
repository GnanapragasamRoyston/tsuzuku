"""La session Spark doit refléter settings.yaml."""

from tsuzuku_pipeline.config import REPO_ROOT
from tsuzuku_pipeline.spark.session import spark_conf


def test_session_uses_settings(spark):
    conf = spark.sparkContext.getConf()
    assert conf.get("spark.driver.memory") == "1g"
    assert spark.conf.get("spark.sql.shuffle.partitions") == "2"
    assert spark.conf.get("spark.sql.session.timeZone") == "UTC"


def test_session_runs_a_job(spark):
    assert spark.range(10).count() == 10


def test_spill_dir_is_on_disk_not_tmp_by_default():
    # /tmp est un tmpfs en RAM sous WSL : Spark ne doit jamais y déverser par défaut.
    conf = spark_conf({"spark": {"driver_memory": "1g"}})
    assert conf["spark.local.dir"] == str(REPO_ROOT / "data" / ".spark-tmp")


def test_spill_dir_configurable(tmp_path):
    conf = spark_conf({"spark": {"driver_memory": "1g", "local_dir": str(tmp_path)}})
    assert conf["spark.local.dir"] == str(tmp_path)
