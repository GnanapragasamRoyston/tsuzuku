"""`make bi-report` : chiffres des vues Power BI → reports/powerbi_summary.json (phase 13).

Le README et le GUIDE Power BI ne citent que des chiffres de ce fichier (CLAUDE.md § 5).
"""

import json

import pytest

from tsuzuku_pipeline import bi_report, key_figures

pytestmark = pytest.mark.db


def _anime(pg, mal, tag=None, drops=(10, 90)):
    mid = pg.execute(
        "INSERT INTO catalog.media (kind, mal_id, title, data_source)"
        " VALUES ('anime', %s, %s, 'mal_kaggle_2020') RETURNING id",
        (mal, f"Anime {mal}"),
    ).fetchone()[0]
    if tag:
        tid = pg.execute(
            "INSERT INTO catalog.tag (name) VALUES (%s) ON CONFLICT (name)"
            " DO UPDATE SET name = EXCLUDED.name RETURNING id",
            (tag,),
        ).fetchone()[0]
        pg.execute("INSERT INTO catalog.media_tag VALUES (%s, %s, 90)", (mid, tid))
    pg.execute(
        "INSERT INTO mart.critical_episode (media_id, critical_episode, critical_drop_share,"
        " nb_drops, nb_completed, drop_rate) VALUES (%s, 1, 0.3, %s, %s, 0)",
        (mid, *drops),
    )


def test_summary_is_read_from_the_bi_views(pg, settings, tmp_path):
    _anime(pg, 1, tag="Isekai", drops=(20, 80))
    _anime(pg, 2, tag="Tragedy", drops=(10, 90))
    _anime(pg, 3, drops=(30, 70))
    settings["paths"] = {"reports": str(tmp_path / "reports")}
    summary = bi_report.run(settings, conn=pg)

    assert summary["anime_with_drop_data"] == 3
    assert summary["anime_with_tags"] == 2
    assert summary["global_drop_rate"] == pytest.approx(60 / 300)
    segments = {s["segment"]: s for s in summary["segments"]}
    assert segments["Isekai"]["nb_anime"] == 1
    assert segments["Autres"]["drop_rate"] == pytest.approx(40 / 200)
    assert summary["view_rows"]["anime_drop"] == 3
    assert summary["view_rows"]["app_totals"] is None  # vues app : absentes de la base du pipeline
    assert summary["database"] == "locale"
    on_disk = json.loads((tmp_path / "reports" / "powerbi_summary.json").read_text())
    assert on_disk == json.loads(json.dumps(summary))


@pytest.mark.parametrize(("host", "label"), [
    ("localhost", "locale"), ("127.0.0.1", "locale"), ("/var/run/postgresql", "locale"),
    ("ep-x-123.eu-central-1.aws.neon.tech", "production"),
    ("db", "inconnue"), ("172.20.0.5", "inconnue"),  # conteneur, réseau local : pas devinés
])  # fmt: skip
def test_database_label_is_never_guessed(host, label):
    assert bi_report.database_label(host) == label


def test_key_figures_copy_the_powerbi_summary(pg, settings, tmp_path):
    _anime(pg, 1, tag="Isekai")
    settings["paths"] = {"reports": str(tmp_path / "reports"), "marts": str(tmp_path / "m"),
                         "parquet": str(tmp_path / "p")}  # fmt: skip
    settings["key_figures"] = {"showcase_titles": []}
    bi_report.run(settings, conn=pg)
    fig = key_figures.run(settings)
    assert fig["powerbi"]["anime_with_tags"] == 1
    assert fig["sources"]["powerbi_summary"]["file"] == "reports/powerbi_summary.json"
    assert "Power BI (phase 13)" in (tmp_path / "reports" / "key_figures.md").read_text()
