"""Rapport de couverture des jaquettes (reports/covers_coverage.json, lot qualité)."""

import json

import pytest

from tsuzuku_pipeline.ingestion import covers_report

pytestmark = pytest.mark.db

CDN = "https://s4.anilist.co/file/anilistcdn/media/manga/cover/large"


def _media(pg, kind, rank, cover=None, source=None, anilist_id=None):
    pg.execute(
        "INSERT INTO catalog.media (kind, anilist_id, title, popularity, cover_url, cover_source,"
        " data_source) VALUES (%s, %s, 't', %s, %s, %s, 'test')",
        (kind, anilist_id, rank, cover, source),
    )


def test_coverage_by_kind_source_and_popularity(pg):
    _media(pg, "anime", 5, "https://cdn.myanimelist.net/images/a.jpg", "jikan")
    _media(pg, "anime", 1500)  # sans jaquette, tranche 1 000 – 10 000
    _media(pg, "anime", None)  # rang inconnu
    _media(pg, "manhwa", 10, f"{CDN}/1.jpg", "anilist", anilist_id=1)
    _media(pg, "manhwa", 20_000, f"{CDN}/2.jpg", "suggestion", anilist_id=2)
    report = covers_report.coverage(pg)

    assert report["by_kind"]["anime"] == {
        "total": 3,
        "with_cover": 1,
        "share": pytest.approx(1 / 3),
    }
    assert report["by_kind"]["manhwa"]["share"] == 1.0
    assert report["by_source"]["anime"] == {"jikan": 1, "none": 2}
    assert report["by_source"]["manhwa"] == {"anilist": 1, "suggestion": 1}
    pop = report["by_popularity"]["anime"]
    assert pop["top_1000"] == {"total": 1, "with_cover": 1, "share": 1.0}
    assert pop["1000_to_10000"] == {"total": 1, "with_cover": 0, "share": 0.0}
    assert pop["unranked"]["total"] == 1
    assert report["by_popularity"]["manhwa"]["beyond_10000"]["with_cover"] == 1
    # Les rangs viennent de MAL (animes) et d'AniList (mangas) : jamais mélangés entre types.
    assert "all" not in report["by_popularity"]


def test_report_is_written_as_json(pg, tmp_path):
    _media(pg, "manga", 1, f"{CDN}/1.jpg", "anilist", anilist_id=1)
    path = covers_report.write(pg, tmp_path)
    assert path.name == "covers_coverage.json"
    assert json.loads(path.read_text())["by_kind"]["manga"]["with_cover"] == 1
