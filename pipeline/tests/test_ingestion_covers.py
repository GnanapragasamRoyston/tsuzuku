"""Couvertures des animes récupérées sur AniList par leur idMal (phase 8)."""

import datetime as dt
import json

import httpx
import pytest

from tsuzuku_pipeline.ingestion import anilist_client, jobs
from tsuzuku_pipeline.ingestion.catalog_loader import fill_anime_covers

pytestmark = pytest.mark.db

DAY = dt.date(2026, 11, 21)
CDN = "https://s4.anilist.co/file/anilistcdn/media/anime/cover/large"


@pytest.fixture
def cov_settings(settings, tmp_path):
    settings["paths"] = {"raw": str(tmp_path / "raw"), "reports": str(tmp_path / "reports")}
    settings["ingestion"] = {
        "reports_subdir": "ingestion",
        "anilist": {"url": "https://anilist.test", "min_interval_s": 0, "timeout_s": 1,
                    "max_retries": 0, "covers_batch_size": 2},
    }  # fmt: skip
    return settings


class FakeCovers:
    """Répond aux requêtes idMal_in : couverture pour les idMal connus, rien pour les autres."""

    def __init__(self, known):
        self.known = known
        self.batches = []

    def __call__(self, request):
        ids = json.loads(request.content)["variables"]["ids"]
        self.batches.append(ids)
        media = [{"idMal": m, "coverImage": {"large": self.known[m]}}
                 for m in ids if m in self.known]  # fmt: skip
        return httpx.Response(200, json={"data": {"Page": {"media": media}}})


def _anime(pg, mal, cover=None, source="mal_kaggle_2020", kind="anime"):
    pg.execute(
        "INSERT INTO catalog.media (kind, mal_id, title, cover_url, data_source)"
        " VALUES (%s, %s, %s, %s, %s)", (kind, mal, f"Anime {mal}", cover, source),
    )  # fmt: skip


def _cover(pg, mal):
    return pg.execute("SELECT cover_url FROM catalog.media WHERE kind = 'anime' AND mal_id = %s",
                      (mal,)).fetchone()[0]  # fmt: skip


def test_covers_fill_only_missing_anime_covers(cov_settings, pg):
    _anime(pg, 1)
    _anime(pg, 2, cover="https://cdn.myanimelist.net/2.jpg")  # déjà là : jamais remplacée
    _anime(pg, 3)
    _anime(pg, 4)  # inconnu d'AniList : reste vide
    _anime(pg, 1, kind="manga", source="anilist")  # même idMal, mais manga : hors périmètre
    fake = FakeCovers({1: f"{CDN}/1.jpg", 2: f"{CDN}/2.jpg", 3: f"{CDN}/3.jpg"})
    report = jobs.anilist_covers(cov_settings, DAY, transport=httpx.MockTransport(fake), conn=pg)
    assert (report["missing"], report["found"], report["updated"]) == (3, 2, 2)
    assert _cover(pg, 1) == f"{CDN}/1.jpg" and _cover(pg, 3) == f"{CDN}/3.jpg"
    assert _cover(pg, 2) == "https://cdn.myanimelist.net/2.jpg"
    assert _cover(pg, 4) is None
    # Lots de covers_batch_size idMal (2) : 3 manquants → 2 requêtes.
    assert sorted(len(b) for b in fake.batches) == [1, 2]
    assert pg.execute("SELECT cover_url FROM catalog.media WHERE kind = 'manga'").fetchone() == (
        None,)  # fmt: skip


def test_covers_rerun_is_idempotent(cov_settings, pg):
    _anime(pg, 1)
    fake = FakeCovers({1: f"{CDN}/1.jpg"})
    jobs.anilist_covers(cov_settings, DAY, transport=httpx.MockTransport(fake), conn=pg)
    again = jobs.anilist_covers(cov_settings, DAY, transport=httpx.MockTransport(fake), conn=pg)
    assert (again["missing"], again["updated"]) == (0, 0)


@pytest.mark.parametrize("url", [
    "http://s4.anilist.co/x.jpg",  # pas de HTTPS
    "https://evil.example/x.jpg",  # autre hôte que le CDN d'AniList
    "javascript:alert(1)",
    None,
])  # fmt: skip
def test_untrusted_cover_urls_are_ignored(pg, url):
    _anime(pg, 1)
    assert fill_anime_covers(pg, {1: url}) == 0
    assert _cover(pg, 1) is None


def test_covers_report_and_raw_file(cov_settings, pg):
    _anime(pg, 1)
    fake = FakeCovers({1: f"{CDN}/1.jpg"})
    jobs.anilist_covers(cov_settings, DAY, transport=httpx.MockTransport(fake), conn=pg)
    raw = json.loads((jobs.raw_dir(cov_settings, "anilist", DAY) / "covers.json").read_text())
    assert raw == {"1": f"{CDN}/1.jpg"}
    reports = jobs.resolve_path(cov_settings, "reports")
    report_path = reports / "ingestion" / "covers_2026-11-21.json"
    assert json.loads(report_path.read_text())["updated"] == 1


def test_parse_covers_skips_incomplete_items():
    page = {"media": [
        {"idMal": 1, "coverImage": {"large": "a"}},
        {"idMal": None},
        {"idMal": 2, "coverImage": None},
        {"idMal": 3, "coverImage": {}},
    ]}  # fmt: skip
    assert anilist_client.parse_covers(page) == {1: "a"}
