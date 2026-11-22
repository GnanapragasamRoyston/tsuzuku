"""Couvertures des animes récupérées sur AniList par leur idMal (phase 8)."""

import datetime as dt
import json

import httpx
import pytest

from tsuzuku_pipeline.ingestion import anilist_client, jobs
from tsuzuku_pipeline.ingestion.catalog_loader import apply_anime_covers

pytestmark = pytest.mark.db

DAY = dt.date(2026, 11, 21)
CDN = "https://s4.anilist.co/file/anilistcdn/media/anime/cover"


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
    """Répond aux requêtes idMal_in : jaquette extraLarge (+ couleur) pour les idMal connus."""

    def __init__(self, known):
        self.known = known
        self.batches = []

    def __call__(self, request):
        ids = json.loads(request.content)["variables"]["ids"]
        self.batches.append(ids)
        media = [{"idMal": m, "coverImage": {"extraLarge": self.known[m], "large": "petite.jpg",
                                             "color": "#AABBCC"}}
                 for m in ids if m in self.known]  # fmt: skip
        return httpx.Response(200, json={"data": {"Page": {"media": media}}})


def _anime(pg, mal, cover=None, source="mal_kaggle_2020", kind="anime", cover_source=None):
    if cover and cover_source is None:
        cover_source = "anilist" if cover.startswith(CDN) else "jikan"
    pg.execute(
        "INSERT INTO catalog.media (kind, mal_id, title, cover_url, cover_source, data_source)"
        " VALUES (%s, %s, %s, %s, %s, %s)",
        (kind, mal, f"Anime {mal}", cover, cover_source, source),
    )  # fmt: skip


def _cover(pg, mal):
    return pg.execute("SELECT cover_url FROM catalog.media WHERE kind = 'anime' AND mal_id = %s",
                      (mal,)).fetchone()[0]  # fmt: skip


def test_covers_fill_missing_and_upgrade_small_anilist_covers(cov_settings, pg):
    _anime(pg, 1)  # sans jaquette
    _anime(pg, 2, cover="https://cdn.myanimelist.net/2.jpg")  # image MAL : jamais remplacée
    _anime(pg, 3, cover=f"{CDN}/medium/3.jpg")  # petite image AniList : remplacée par la grande
    _anime(pg, 4)  # inconnu d'AniList : reste vide
    _anime(pg, 5, cover="https://cdn.myanimelist.net/5.jpg", cover_source="suggestion")
    _anime(pg, 1, kind="manga", source="anilist")  # même idMal, mais manga : hors périmètre
    fake = FakeCovers({m: f"{CDN}/large/{m}.jpg" for m in (1, 2, 3, 5)})
    report = jobs.anilist_covers(cov_settings, DAY, transport=httpx.MockTransport(fake), conn=pg)
    # Demandés : sans jaquette (1, 4) et petite AniList (3) ; ni MAL (2) ni validée par Royston (5).
    assert (report["requested"], report["found"], report["updated"]) == (3, 2, 2)
    assert _cover(pg, 1) == f"{CDN}/large/1.jpg" and _cover(pg, 3) == f"{CDN}/large/3.jpg"
    assert _cover(pg, 2) == "https://cdn.myanimelist.net/2.jpg"
    assert _cover(pg, 5) == "https://cdn.myanimelist.net/5.jpg"
    assert _cover(pg, 4) is None and report["still_missing"] == 1
    assert pg.execute(
        "SELECT cover_source, cover_color FROM catalog.media WHERE kind = 'anime' AND mal_id = 1"
    ).fetchone() == ("anilist", "#aabbcc")
    assert sorted(len(b) for b in fake.batches) == [1, 2]
    assert pg.execute("SELECT cover_url FROM catalog.media WHERE kind = 'manga'").fetchone() == (
        None,)  # fmt: skip


def test_covers_rerun_is_idempotent(cov_settings, pg):
    _anime(pg, 1)
    fake = FakeCovers({1: f"{CDN}/large/1.jpg"})
    jobs.anilist_covers(cov_settings, DAY, transport=httpx.MockTransport(fake), conn=pg)
    again = jobs.anilist_covers(cov_settings, DAY, transport=httpx.MockTransport(fake), conn=pg)
    assert (again["requested"], again["updated"]) == (0, 0)


@pytest.mark.parametrize("url", [
    "http://s4.anilist.co/x.jpg",  # pas de HTTPS
    "https://evil.example/x.jpg",  # autre hôte que le CDN d'AniList
    "javascript:alert(1)",
    f"{CDN}/large/default.jpg",  # image par défaut d'AniList : pas une jaquette
    None,
])  # fmt: skip
def test_untrusted_or_placeholder_cover_urls_are_ignored(pg, url):
    _anime(pg, 1)
    assert apply_anime_covers(pg, {1: {"url": url, "color": None}}) == 0
    assert _cover(pg, 1) is None


def test_covers_report_and_raw_file(cov_settings, pg):
    _anime(pg, 1)
    fake = FakeCovers({1: f"{CDN}/large/1.jpg"})
    jobs.anilist_covers(cov_settings, DAY, transport=httpx.MockTransport(fake), conn=pg)
    raw = json.loads((jobs.raw_dir(cov_settings, "anilist", DAY) / "covers.json").read_text())
    assert raw == {"1": {"url": f"{CDN}/large/1.jpg", "color": "#aabbcc"}}
    reports = jobs.resolve_path(cov_settings, "reports")
    report_path = reports / "ingestion" / "covers_2026-11-21.json"
    assert json.loads(report_path.read_text())["updated"] == 1


def test_parse_covers_prefers_extra_large_and_skips_incomplete_items():
    page = {"media": [
        {"idMal": 1, "coverImage": {"extraLarge": "https://x/large/a.jpg", "large": "b"}},
        {"idMal": None},
        {"idMal": 2, "coverImage": None},
        {"idMal": 3, "coverImage": {}},
        {"idMal": 4, "coverImage": {"extraLarge": "https://x/large/default.jpg"}},
    ]}  # fmt: skip
    assert anilist_client.parse_covers(page) == {1: {"url": "https://x/large/a.jpg", "color": None}}


def test_jikan_sync_never_erases_an_anilist_cover(pg):
    """Anime inséré par Jikan sans image, complété par AniList : la synchro Jikan suivante ne doit
    pas remettre la jaquette à vide (elle clignotait d'un jour à l'autre, revue du lot qualité)."""
    from tsuzuku_pipeline.ingestion.catalog_loader import upsert_jikan_anime
    from tsuzuku_pipeline.ingestion.records import MediaRecord

    rec = MediaRecord(kind="anime", title="Nouveau", mal_id=99)
    upsert_jikan_anime(pg, [rec])
    apply_anime_covers(pg, {99: {"url": f"{CDN}/large/99.jpg", "color": "#123456"}})
    upsert_jikan_anime(pg, [rec])  # Jikan, toujours sans image
    assert _cover(pg, 99) == f"{CDN}/large/99.jpg"
    # Et une image Jikan ne remplace pas la grande image AniList.
    upsert_jikan_anime(pg, [MediaRecord(kind="anime", title="Nouveau", mal_id=99,
                                        cover_url="https://cdn.myanimelist.net/images/99.jpg",
                                        cover_source="jikan")])  # fmt: skip
    assert _cover(pg, 99) == f"{CDN}/large/99.jpg"
