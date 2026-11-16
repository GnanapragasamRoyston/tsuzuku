"""Test de bout en bout de `make data` sur des mini-CSV (sans réseau)."""

import json

import pytest
from test_to_parquet import ANIME_HEADER, ANIME_ROWS, TAIL

from tsuzuku_pipeline import data_cli

ADULT_ROW = (
    '2,Adult,6.0,Hentai,Unknown,x,OVA,2,"Jan 1, 2001",Unknown,Unknown,Unknown,Unknown,Unknown,'
    "25 min. per ep.,Rx - Hentai,Unknown,9,10" + TAIL
)
# Utilisateurs 0 à 39 : chacun a vu les animes 1 (ok), 2 (adulte) et 77 (orphelin).
ANIMELIST = "user_id,anime_id,rating,watching_status,watched_episodes\n" + "".join(
    f"{u},1,8,2,26\n{u},2,5,4,1\n{u},77,7,1,3\n" for u in range(40)
)
RATING = "user_id,anime_id,rating\n" + "".join(f"{u},1,8\n" for u in range(40))


@pytest.fixture
def project(tmp_path, settings):
    raw = tmp_path / "raw"
    raw.mkdir()
    (raw / "anime.csv").write_text(
        "\n".join([ANIME_HEADER, *ANIME_ROWS, ADULT_ROW]) + "\n", encoding="utf-8"
    )
    (raw / "anime_with_synopsis.csv").write_text(
        'MAL_ID,Name,Score,Genres,sypnopsis\n1,A,8,Action,"Hello"\n2,B,6,Hentai,"x"\n',
        encoding="utf-8",
    )
    (raw / "watching_status.csv").write_text(
        "status, description\n1,Currently Watching\n2,Completed\n4,Dropped\n", encoding="utf-8"
    )
    (raw / "animelist.csv").write_text(ANIMELIST, encoding="utf-8")
    (raw / "rating_complete.csv").write_text(RATING, encoding="utf-8")

    settings["paths"] = {
        "raw": str(raw),
        "parquet": str(tmp_path / "parquet"),
        "samples": str(tmp_path / "samples"),
        "reports": str(tmp_path / "reports"),
    }
    settings["data"] = {
        **settings["data"],
        "kaggle_dataset": "owner/ds",
        "license": "CC0-1.0",
        "files": [],
    }
    return tmp_path, settings


SPARK_STEPS = ["staging", "clean", "quality", "sample"]


def test_full_run_produces_clean_tables_and_report(spark, project):
    root, settings = project
    data_cli.run(settings, steps=SPARK_STEPS, spark=spark)

    clean = root / "parquet" / "clean"
    anime_ids = {
        r[0] for r in spark.read.parquet(str(clean / "anime")).select("anime_id").collect()
    }
    assert anime_ids == {1, 5, 9}  # 2 (Rx) exclu

    animelist = spark.read.parquet(str(clean / "animelist"))
    assert {r[0] for r in animelist.select("anime_id").distinct().collect()} == {1}
    assert animelist.count() == 40

    synopsis_ids = {r[0] for r in spark.read.parquet(str(clean / "synopsis")).collect()}
    assert synopsis_ids == {1}

    report = json.loads((root / "reports" / "data_quality.json").read_text(encoding="utf-8"))
    assert report["license"] == "CC0-1.0"
    assert report["watching_status"] == {
        "1": "Currently Watching",
        "2": "Completed",
        "4": "Dropped",
    }
    assert report["tables"]["anime"]["adult_total"] == 1
    assert report["filters"]["animelist"] == {
        "rows_before": 120,
        "removed_null_keys": 0,
        "removed_unknown_status": 0,
        "removed_duplicates": 0,
        "removed_adult": 40,
        "removed_orphan": 40,
        "orphan_anime_ids": 1,
        "rows_after": 40,
    }
    assert report["consistency"]["rating_complete_pairs_missing_from_animelist"] == 0
    assert (root / "reports" / "data_quality.md").is_file()

    sample = spark.read.parquet(str(root / "samples" / "animelist"))
    assert 0 < sample.count() < 40


def test_second_run_skips_finished_steps(spark, project):
    root, settings = project
    data_cli.run(settings, steps=SPARK_STEPS, spark=spark)
    marker = root / "parquet" / "clean" / "animelist" / "_SUCCESS"
    report = root / "reports" / "data_quality.json"
    before = (marker.stat().st_mtime_ns, report.stat().st_mtime_ns)

    data_cli.run(settings, steps=SPARK_STEPS, spark=spark)
    assert (marker.stat().st_mtime_ns, report.stat().st_mtime_ns) == before


def test_force_rebuilds(spark, project):
    root, settings = project
    data_cli.run(settings, steps=["staging", "clean"], spark=spark)
    marker = root / "parquet" / "clean" / "animelist" / "_SUCCESS"
    before = marker.stat().st_mtime_ns
    data_cli.run(settings, steps=["clean"], spark=spark, force=True)
    assert marker.stat().st_mtime_ns != before


def test_rebuilding_upstream_makes_downstream_stale(spark, project):
    # Refaire clean seul (ex. après un changement de règle) ne doit pas laisser un rapport et un
    # échantillon calculés sur l'ancienne version : le run suivant doit les refaire.
    root, settings = project
    data_cli.run(settings, steps=SPARK_STEPS, spark=spark)
    report = root / "reports" / "data_quality.json"
    sample = root / "samples" / "animelist" / "_SUCCESS"
    before = (report.stat().st_mtime_ns, sample.stat().st_mtime_ns)

    data_cli.run(settings, steps=["clean"], spark=spark, force=True)
    data_cli.run(settings, steps=SPARK_STEPS, spark=spark)
    after = (report.stat().st_mtime_ns, sample.stat().st_mtime_ns)
    assert after[0] != before[0]
    assert after[1] != before[1]


def test_partial_output_is_rebuilt(spark, project):
    root, settings = project
    data_cli.run(settings, steps=["staging"], spark=spark)
    (root / "parquet" / "staging" / "animelist" / "_SUCCESS").unlink()  # job interrompu
    data_cli.run(settings, steps=["staging"], spark=spark)
    assert (root / "parquet" / "staging" / "animelist" / "_SUCCESS").is_file()


def test_unknown_step_rejected(settings):
    with pytest.raises(ValueError, match="inconnues"):
        data_cli.run(settings, steps=["nope"])
