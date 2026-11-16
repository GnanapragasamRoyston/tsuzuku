"""Test de bout en bout de `make spark` : mini couche clean → marts → Postgres de test."""

import json

import pytest

from tsuzuku_pipeline import spark_cli

pytestmark = pytest.mark.db

LIST_SCHEMA = "user_id int, anime_id int, score int, watching_status int, watched_episodes int"


@pytest.fixture
def project(spark, tmp_path, settings, pg, pg_url, monkeypatch):
    clean = tmp_path / "parquet" / "clean"
    spark.createDataFrame(
        [(1, "A", None, 4, "TV", 24.0, 2001, ["S1"], "Manga", "PG-13", 10, ["Action"]),
         (2, "B", "B en", 12, "TV", 24.0, 2005, ["S2"], None, "G", 20, ["Action", "Drama"])],
        "anime_id int, name string, english_name string, episodes int, type string,"
        " duration_min double, start_year int, studios array<string>, source string,"
        " rating string, popularity int, genres array<string>",
    ).write.parquet(str(clean / "anime"))  # fmt: skip
    spark.createDataFrame([(1, "Synopsis A")], "anime_id int, synopsis string").write.parquet(
        str(clean / "synopsis")
    )
    spark.createDataFrame(
        [(1, "Currently Watching"), (2, "Completed"), (3, "On Hold"), (4, "Dropped"),
         (6, "Plan to Watch")],
        "status int, description string",
    ).write.parquet(str(clean / "watching_status"))  # fmt: skip
    rows = [(u, 1, 8, 2, 4) for u in range(6)] + [(10 + u, 1, 0, 4, u % 3 + 1) for u in range(6)]
    rows += [(30, 2, 0, 4, 2), (31, 2, 9, 2, 12)]
    spark.createDataFrame(rows, LIST_SCHEMA).write.parquet(str(clean / "animelist"))

    settings["paths"] = {
        "parquet": str(tmp_path / "parquet"),
        "marts": str(tmp_path / "marts"),
        "reports": str(tmp_path / "reports"),
    }
    settings["critical_episode"] = {"no_return_risk_ratio": 0.25, "min_drops": 5, "min_episodes": 3}
    settings["retention"] = {"min_interactions": 1, "min_anime": 1}
    monkeypatch.setenv("DATABASE_URL", pg_url)  # jamais la base de dev
    return tmp_path, settings


def test_end_to_end_marts_and_load(spark, project, pg):
    root, settings = project
    spark_cli.run(settings, spark=spark)

    summary = json.loads((root / "reports" / "marts_summary.json").read_text(encoding="utf-8"))
    assert summary["checks"] == {"curves_not_ending_at_1": 0, "rates_out_of_range": 0}
    assert summary["critical_episode"]["anime"] == 1  # anime 2 : 1 seul drop < min_drops

    assert pg.execute("SELECT count(*) FROM catalog.media").fetchone()[0] == 2
    crit = pg.execute(
        "SELECT m.mal_id, c.critical_episode, c.nb_drops FROM mart.critical_episode c"
        " JOIN catalog.media m ON m.id = c.media_id"
    ).fetchall()
    assert crit == [(1, 1, 6)]
    genres = dict(pg.execute("SELECT genre, nb_anime FROM mart.retention_by_genre").fetchall())
    assert genres == {"Action": 2, "Drama": 1}


def test_threshold_change_recomputes_marts(spark, project):
    root, settings = project
    spark_cli.run(settings, steps=["marts"], spark=spark)
    summary = root / "reports" / "marts_summary.json"
    before = summary.stat().st_mtime_ns

    spark_cli.run(settings, steps=["marts"], spark=spark)
    assert summary.stat().st_mtime_ns == before  # rien n'a changé : sautée

    settings["critical_episode"]["no_return_risk_ratio"] = 0.5  # seuil modifié, sans --force
    spark_cli.run(settings, steps=["marts"], spark=spark)
    assert summary.stat().st_mtime_ns != before


def test_load_refuses_inconsistent_summary(spark, project, pg):
    root, settings = project
    spark_cli.run(settings, steps=["marts"], spark=spark)
    path = root / "reports" / "marts_summary.json"
    summary = json.loads(path.read_text(encoding="utf-8"))
    summary["checks"]["curves_not_ending_at_1"] = 3
    path.write_text(json.dumps(summary), encoding="utf-8")

    with pytest.raises(RuntimeError, match="incohérents"):
        spark_cli.run(settings, steps=["load"], spark=spark)
    assert pg.execute("SELECT to_regclass('mart.drop_curve') IS NULL OR "
                      "(SELECT count(*) = 0 FROM mart.drop_curve)").fetchone()[0]  # fmt: skip


def test_rerun_is_idempotent(spark, project, pg):
    _, settings = project
    spark_cli.run(settings, spark=spark)
    ids = pg.execute("SELECT mal_id, id FROM catalog.media ORDER BY 1").fetchall()
    curve = pg.execute("SELECT count(*) FROM mart.drop_curve").fetchone()[0]

    spark_cli.run(settings, spark=spark)  # marts à jour (sautés), load rejoué
    assert pg.execute("SELECT mal_id, id FROM catalog.media ORDER BY 1").fetchall() == ids
    assert pg.execute("SELECT count(*) FROM mart.drop_curve").fetchone()[0] == curve
