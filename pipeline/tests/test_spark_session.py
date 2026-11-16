"""La session Spark doit refléter settings.yaml."""


def test_session_uses_settings(spark):
    conf = spark.sparkContext.getConf()
    assert conf.get("spark.driver.memory") == "1g"
    assert spark.conf.get("spark.sql.shuffle.partitions") == "2"
    assert spark.conf.get("spark.sql.session.timeZone") == "UTC"


def test_session_runs_a_job(spark):
    assert spark.range(10).count() == 10
