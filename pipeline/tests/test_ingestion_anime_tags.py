"""Tags AniList des animes, par leur idMal (phase 13 : segment « Isekai » de Power BI).

Les animes du dataset MAL 2020 n'ont ni tags ni identifiant AniList : sans eux, impossible de
mesurer la rétention des isekai. Seuls les animes qui ont des données de drop (mart) sont demandés.
"""

import datetime as dt
import json

import httpx
import pytest

from tsuzuku_pipeline.ingestion import anilist_client, jobs
from tsuzuku_pipeline.ingestion.http import HttpError

pytestmark = pytest.mark.db

DAY = dt.date(2026, 11, 28)


@pytest.fixture
def tag_settings(settings, tmp_path):
    settings["paths"] = {"raw": str(tmp_path / "raw"), "reports": str(tmp_path / "reports")}
    settings["ingestion"] = {
        "reports_subdir": "ingestion",
        "anilist": {"url": "https://anilist.test", "min_interval_s": 0, "timeout_s": 1,
                    "max_retries": 0, "covers_batch_size": 2, "tag_min_rank": 60},
    }  # fmt: skip
    return settings


class FakeTags:
    """Répond aux requêtes idMal_in : identifiant AniList (= idMal + 1000) et tags connus."""

    def __init__(self, known):
        self.known = known
        self.batches = []

    def __call__(self, request):
        ids = json.loads(request.content)["variables"]["ids"]
        self.batches.append(ids)
        media = [{"id": m + 1000, "idMal": m, "tags": self.known[m]}
                 for m in ids if m in self.known]  # fmt: skip
        return httpx.Response(200, json={"data": {"Page": {"media": media}}})


def _anime(pg, mal, with_drop_data=True, kind="anime", anilist_id=None):
    mid = pg.execute(
        "INSERT INTO catalog.media (kind, mal_id, anilist_id, title, data_source)"
        " VALUES (%s, %s, %s, %s, 'mal_kaggle_2020') RETURNING id",
        (kind, mal, anilist_id, f"Anime {mal}"),
    ).fetchone()[0]
    if with_drop_data:
        pg.execute(
            "INSERT INTO mart.critical_episode (media_id, critical_episode, critical_drop_share,"
            " nb_drops, nb_completed, drop_rate) VALUES (%s, 1, 0.3, 10, 90, 0.1)",
            (mid,),
        )
    return mid


def _tags(pg, mid):
    return pg.execute(
        "SELECT t.name, mt.rank FROM catalog.media_tag mt JOIN catalog.tag t ON t.id = mt.tag_id"
        " WHERE mt.media_id = %s ORDER BY t.name",
        (mid,),
    ).fetchall()


ISEKAI = {"name": "Isekai", "rank": 94, "isAdult": False}


def _run(settings, fake, pg):
    return jobs.anilist_anime_tags(settings, DAY, transport=httpx.MockTransport(fake), conn=pg)


def test_tags_and_anilist_id_are_stored_for_animes_with_drop_data(tag_settings, pg):
    a1 = _anime(pg, 1)
    a2 = _anime(pg, 2)
    a3 = _anime(pg, 3)  # inconnu d'AniList : rien n'est écrit
    a4 = _anime(pg, 4, with_drop_data=False)  # sans données de drop : pas demandé
    fake = FakeTags({
        1: [ISEKAI, {"name": "Male Protagonist", "rank": 80, "isAdult": False}],
        2: [{"name": "Tragedy", "rank": 70, "isAdult": False}],
        4: [ISEKAI],
    })  # fmt: skip
    report = _run(tag_settings, fake, pg)
    assert (report["requested"], report["found"], report["tagged"]) == (3, 2, 2)
    assert sorted(len(b) for b in fake.batches) == [1, 2]  # lots de covers_batch_size
    assert _tags(pg, a1) == [("Isekai", 94), ("Male Protagonist", 80)]
    assert _tags(pg, a2) == [("Tragedy", 70)]
    assert _tags(pg, a3) == [] and _tags(pg, a4) == []
    ids = dict(pg.execute("SELECT mal_id, anilist_id FROM catalog.media WHERE kind = 'anime'"))
    assert ids == {1: 1001, 2: 1002, 3: None, 4: None}


def test_adult_and_weak_tags_are_never_kept(tag_settings, pg):
    mid = _anime(pg, 1)
    fake = FakeTags({1: [ISEKAI, {"name": "Nudity", "rank": 90, "isAdult": True},
                         {"name": "Cooking", "rank": 40, "isAdult": False}]})  # fmt: skip
    jobs.anilist_anime_tags(tag_settings, DAY, transport=httpx.MockTransport(fake), conn=pg)
    assert _tags(pg, mid) == [("Isekai", 94)]


def test_rerun_asks_nothing_again(tag_settings, pg):
    _anime(pg, 1)
    fake = FakeTags({1: [ISEKAI]})
    jobs.anilist_anime_tags(tag_settings, DAY, transport=httpx.MockTransport(fake), conn=pg)
    again = jobs.anilist_anime_tags(tag_settings, DAY, transport=httpx.MockTransport(fake), conn=pg)
    assert (again["requested"], again["tagged"]) == (0, 0)


def test_an_anilist_id_already_used_elsewhere_is_not_stolen(tag_settings, pg):
    """anilist_id est unique : s'il appartient déjà à une autre œuvre, l'anime garde NULL (aucune
    erreur de clé, aucun rattachement deviné) mais ses tags sont bien enregistrés."""
    _anime(pg, 900, with_drop_data=False, kind="manga", anilist_id=1001)
    mid = _anime(pg, 1)
    fake = FakeTags({1: [ISEKAI]})
    report = _run(tag_settings, fake, pg)
    assert report["tagged"] == 1 and _tags(pg, mid) == [("Isekai", 94)]
    assert pg.execute("SELECT anilist_id FROM catalog.media WHERE id = %s", (mid,)).fetchone() == (
        None,)  # fmt: skip


def test_each_batch_is_saved_as_it_arrives(tag_settings, pg):
    """Un échec au milieu (AniList en 5xx) garde les lots déjà reçus : relancer reprend là où on
    s'était arrêté (revue de la phase 13)."""
    a1, a2 = _anime(pg, 1), _anime(pg, 2)
    _anime(pg, 3)
    fake = FakeTags({1: [ISEKAI], 2: [ISEKAI], 3: [ISEKAI]})

    def failing_second_batch(request):
        if fake.batches:  # 2e lot (covers_batch_size = 2 : [1, 2] puis [3])
            return httpx.Response(503)
        return fake(request)

    with pytest.raises(HttpError):
        jobs.anilist_anime_tags(tag_settings, DAY, transport=httpx.MockTransport(
            failing_second_batch), conn=pg)  # fmt: skip
    assert _tags(pg, a1) == [("Isekai", 94)] and _tags(pg, a2) == [("Isekai", 94)]
    again = _run(tag_settings, FakeTags({3: [ISEKAI]}), pg)
    assert (again["requested"], again["tagged"]) == (1, 1)


def test_report_and_raw_file(tag_settings, pg):
    _anime(pg, 1)
    fake = FakeTags({1: [ISEKAI]})
    jobs.anilist_anime_tags(tag_settings, DAY, transport=httpx.MockTransport(fake), conn=pg)
    raw = json.loads((jobs.raw_dir(tag_settings, "anilist", DAY) / "anime_tags.json").read_text())
    assert raw == {"1": {"anilist_id": 1001, "tags": [["Isekai", 94]]}}
    report = jobs.resolve_path(tag_settings, "reports") / "ingestion" / "anime_tags_2026-11-28.json"
    assert json.loads(report.read_text())["tagged"] == 1


def test_parse_anime_tags_skips_incomplete_items():
    page = {"media": [
        {"id": 5, "idMal": 1, "tags": [ISEKAI]},
        {"id": 6, "idMal": None, "tags": [ISEKAI]},  # sans idMal : impossible à rattacher
        {"id": None, "idMal": 2, "tags": [ISEKAI]},
        {"id": 7, "idMal": 3, "tags": None},  # connu, sans tag : identifiant gardé
    ]}  # fmt: skip
    assert anilist_client.parse_anime_tags(page, tag_min_rank=60) == {
        1: {"anilist_id": 5, "tags": [("Isekai", 94)]},
        3: {"anilist_id": 7, "tags": []},
    }
