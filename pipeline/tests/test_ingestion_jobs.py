"""Tâches d'ingestion de bout en bout : API simulées → fichiers bruts → Postgres → contrôle."""

import datetime as dt
import json

import httpx
import pytest

from tsuzuku_pipeline.ingestion import jobs
from tsuzuku_pipeline.ingestion.jobs import IngestionError

pytestmark = pytest.mark.db

DAY = dt.date(2026, 11, 20)


@pytest.fixture
def ing_settings(settings, tmp_path):
    settings["paths"] = {"raw": str(tmp_path / "raw"), "reports": str(tmp_path / "reports")}
    settings["ingestion"] = {
        "reports_subdir": "ingestion",
        "jikan": {"base_url": "https://jikan.test/v4", "min_interval_s": 0, "timeout_s": 1,
                  "max_retries": 0, "max_season_pages": 3, "max_failure_share": 0.2},
        "anilist": {"url": "https://anilist.test", "min_interval_s": 0, "timeout_s": 1,
                    "max_retries": 0, "per_page": 3, "max_pages": 5, "tag_min_rank": 60,
                    "min_share_of_expected": 0.5},
    }  # fmt: skip
    return settings


def _anime(mal_id, **extra):
    return {"mal_id": mal_id, "title": f"Anime {mal_id}", "type": "ONA", "episodes": 99,
            "rating": "PG-13 - Teens 13 or older", "score": 8.0, "members": 1000,
            "genres": [{"name": "Action"}], "studios": [{"name": "Nouveau"}],
            "images": {"jpg": {"large_image_url": f"{mal_id}.jpg"}}, **extra}  # fmt: skip


class FakeJikan:
    def __init__(self, season=None, failing=()):
        self.season = season if season is not None else [
            _anime(1), _anime(500), _anime(666, rating="Rx - Hentai")]  # fmt: skip
        self.failing = set(failing)
        self.dropped = 3

    def __call__(self, request):
        path = request.url.path.removeprefix("/v4")
        if path == "/seasons/now":
            return httpx.Response(200, json={"data": self.season,
                                             "pagination": {"has_next_page": False}})  # fmt: skip
        mal_id = int(path.split("/")[2])
        if path.endswith("/statistics"):
            if mal_id in self.failing:
                return httpx.Response(404)
            return httpx.Response(200, json={"data": {
                "watching": 10, "completed": 20, "on_hold": 1, "dropped": self.dropped,
                "plan_to_watch": 40}})  # fmt: skip
        return httpx.Response(200, json={"data": _anime(mal_id)})


def _kaggle_anime(pg):
    """Anime du dataset 2020 : ses champs-features ne doivent jamais être modifiés par Jikan."""
    pg.execute(
        "INSERT INTO catalog.media (kind, mal_id, title, format, episodes, creators, data_source)"
        " VALUES ('anime', 1, 'Anime 1', 'TV', 12, '{Ancien}', 'mal_kaggle_2020')"
    )


def _run_jikan(settings, pg, fake, watchlist=(777,)):
    transport = httpx.MockTransport(fake)
    jobs.jikan_collect(settings, DAY, transport=transport, watchlist=list(watchlist), today=DAY)
    jobs.jikan_fetch_stats(settings, DAY, transport=transport, today=DAY)
    jobs.jikan_load(settings, DAY, conn=pg)
    return jobs.jikan_quality(settings, DAY, conn=pg)


def test_jikan_full_run_and_training_rows_protected(ing_settings, pg):
    _kaggle_anime(pg)
    report = _run_jikan(ing_settings, pg, FakeJikan())
    assert report["ok"] and report["targets"] == 3 and report["rows_for_day"] == 3  # adulte exclu
    kaggle = pg.execute("SELECT format, episodes, creators, cover_url, data_source"
                        " FROM catalog.media WHERE mal_id = 1").fetchone()  # fmt: skip
    # Features du dataset 2020 intactes ; seule la couverture est complétée.
    assert kaggle == ("TV", 12, ["Ancien"], "1.jpg", "mal_kaggle_2020")
    new = pg.execute("SELECT format, data_source FROM catalog.media WHERE mal_id = 500").fetchone()
    assert new == ("ONA", "jikan")
    genres = pg.execute("SELECT g.name FROM catalog.media_genre mg JOIN catalog.genre g"
                        " ON g.id = mg.genre_id JOIN catalog.media m ON m.id = mg.media_id"
                        " WHERE m.mal_id = 500").fetchall()  # fmt: skip
    assert genres == [("Action",)]
    # Le rapport et les fichiers bruts existent.
    raw = ing_settings["paths"]["raw"]
    assert json.loads(open(f"{raw}/jikan/2026-11-20/stats.json").read())["failures"] == []


def test_jikan_rerun_same_day_is_idempotent(ing_settings, pg):
    fake = FakeJikan()
    _run_jikan(ing_settings, pg, fake)
    fake.dropped = 9
    _run_jikan(ing_settings, pg, fake)
    rows = pg.execute("SELECT count(*), max(dropped) FROM catalog.media_daily_stats"
                      " WHERE snapshot_date = %s", (DAY,)).fetchone()  # fmt: skip
    assert rows == (3, 9)  # mêmes lignes, valeurs mises à jour
    assert pg.execute("SELECT count(*) FROM catalog.media WHERE mal_id = 500").fetchone()[0] == 1


def test_isolated_failure_keeps_the_anime_with_score_and_members(ing_settings, pg):
    ing_settings["ingestion"]["jikan"]["max_failure_share"] = 0.5
    report = _run_jikan(ing_settings, pg, FakeJikan(failing={500}))
    assert report["ok"] and report["rows_for_day"] == 3  # l'anime en échec garde sa ligne
    assert report["failures"][0]["mal_id"] == 500
    row = pg.execute(
        "SELECT s.members, s.dropped FROM catalog.media_daily_stats s"
        " JOIN catalog.media m ON m.id = s.media_id WHERE m.mal_id = 500"
    ).fetchone()
    assert row == (1000, None)  # membres (fiche) connus, détail par statut inconnu


def test_watchlist_anime_is_marked_out_of_season(ing_settings, pg):
    _run_jikan(ing_settings, pg, FakeJikan())
    rows = dict(pg.execute("SELECT m.mal_id, s.in_season FROM catalog.media_daily_stats s"
                           " JOIN catalog.media m ON m.id = s.media_id").fetchall())  # fmt: skip
    assert rows == {1: True, 500: True, 777: False}


def test_too_many_failures_stop_early_and_fail_the_task(ing_settings, pg):
    fake = FakeJikan(failing={1, 500})
    transport = httpx.MockTransport(fake)
    jobs.jikan_collect(ing_settings, DAY, transport=transport, watchlist=[777], today=DAY)
    with pytest.raises(IngestionError, match="seuil"):  # 1 échec sur 3 > 20 % : arrêt immédiat
        jobs.jikan_fetch_stats(ing_settings, DAY, transport=transport, today=DAY)
    stats = json.loads(open(f"{ing_settings['paths']['raw']}/jikan/2026-11-20/stats.json").read())
    assert len(stats["failures"]) == 1  # le 2e anime en échec n'a pas été tenté


@pytest.mark.parametrize("step", ["collect", "fetch_stats"])
def test_collecting_for_a_past_date_is_refused(ing_settings, step):
    # Jikan ne donne que l'état actuel : le ranger sous une date passée écraserait son snapshot.
    transport = httpx.MockTransport(FakeJikan())
    with pytest.raises(IngestionError, match="refusé"):
        if step == "collect":
            jobs.jikan_collect(ing_settings, DAY, transport=transport, watchlist=[],
                               today=DAY + dt.timedelta(days=1))  # fmt: skip
        else:
            jobs.jikan_fetch_stats(ing_settings, DAY, transport=transport,
                                   today=DAY + dt.timedelta(days=1))  # fmt: skip


def test_empty_season_fails(ing_settings):
    with pytest.raises(IngestionError, match="aucune"):
        jobs.jikan_collect(ing_settings, DAY, transport=httpx.MockTransport(FakeJikan(season=[])),
                           watchlist=[], today=DAY)  # fmt: skip


def test_load_without_previous_step_fails_clearly(ing_settings, pg):
    with pytest.raises(IngestionError, match="absent"):
        jobs.jikan_load(ing_settings, DAY, conn=pg)


# --- AniList -----------------------------------------------------------------------------------


def _title(aid, country="JP", mal=None, **extra):
    return {"id": aid, "idMal": mal, "countryOfOrigin": country, "format": "MANGA",
            "status": "RELEASING", "chapters": 10, "isAdult": False,
            "title": {"romaji": f"Titre {aid}", "english": None}, "startDate": {"year": 2020},
            "genres": ["Drama"], "tags": [{"name": "Tragedy", "rank": 80, "isAdult": False}],
            "description": "Résumé", "coverImage": {"large": f"{aid}.jpg"}, "source": "ORIGINAL",
            "staff": {"edges": []}, **extra}  # fmt: skip


class FakeAniList:
    def __init__(self):
        self.pages = {
            1: {"pageInfo": {"hasNextPage": True},
                "media": [_title(1, mal=10), _title(2, "KR", mal=10),
                          _title(3, isAdult=True, genres=["Hentai"])]},
            2: {"pageInfo": {"hasNextPage": False},
                "media": [_title(4, "CN"), _title(1, mal=10)]},
        }  # fmt: skip

    def __call__(self, request):
        page = json.loads(request.content)["variables"]["page"]
        return httpx.Response(200, json={"data": {"Page": self.pages[page]}})


def _run_anilist(settings, pg):
    jobs.anilist_fetch(settings, DAY, transport=httpx.MockTransport(FakeAniList()))
    load = jobs.anilist_load(settings, DAY, conn=pg)
    return load, jobs.anilist_quality(settings, DAY, conn=pg)


def test_anilist_full_run(ing_settings, pg):
    load, report = _run_anilist(ing_settings, pg)
    assert report["ok"] and report["fetched"] == 5 and report["pages"] == 2
    # 1 adulte écarté, 1 doublon de page (titre 1 vu deux fois).
    assert (load["skipped"], load["duplicates"], load["inserted"]) == (1, 1, 3)
    assert report["catalog_by_kind"] == {"manga": 1, "manhwa": 1, "manhua": 1}
    # idMal 10 en manga (titre 1) et en manhwa (titre 2) : types différents, pas de conflit.
    assert load["mal_id_cleared"] == 0
    tags = pg.execute("SELECT count(*) FROM catalog.media_tag").fetchone()[0]
    assert tags == 3
    # Rang de popularité = position dans le tri (1 = le plus populaire).
    assert pg.execute("SELECT popularity FROM catalog.media WHERE anilist_id = 4"
                      ).fetchone()[0] == 4  # fmt: skip


def test_anilist_rerun_updates_without_duplicates(ing_settings, pg):
    _run_anilist(ing_settings, pg)
    load, _ = _run_anilist(ing_settings, pg)
    assert (load["inserted"], load["updated"]) == (0, 3)
    assert pg.execute("SELECT count(*) FROM catalog.media WHERE data_source = 'anilist'"
                      ).fetchone()[0] == 3  # fmt: skip


def test_anilist_mal_id_conflicts_are_cleared_not_fatal(ing_settings, pg):
    from tsuzuku_pipeline.ingestion.catalog_loader import upsert_anilist_media
    from tsuzuku_pipeline.ingestion.records import MediaRecord

    def rec(aid, mal, rank):
        return MediaRecord(kind="manga", title=f"T{aid}", anilist_id=aid, mal_id=mal,
                           popularity=rank)  # fmt: skip

    # (a) même idMal dans le lot, même type : le mieux classé le garde.
    counts = upsert_anilist_media(pg, [rec(1, 42, 1), rec(2, 42, 2)])
    assert counts["mal_id_cleared"] == 1
    assert dict(pg.execute("SELECT anilist_id, mal_id FROM catalog.media").fetchall()) == {
        1: 42, 2: None}  # fmt: skip
    # (b) idMal déjà porté en base par un AUTRE titre AniList : mis à null, rien n'échoue.
    counts = upsert_anilist_media(pg, [rec(1, 42, 1), rec(3, 42, 2)])
    assert counts["mal_id_cleared"] == 1
    # (c) relance identique : idempotente.
    again = upsert_anilist_media(pg, [rec(1, 42, 1), rec(3, 42, 2)])
    assert (again["inserted"], again["updated"]) == (0, 2)
    # Le titre 2, absent du dernier lot, perd son rang (sorti du top) mais reste au catalogue.
    assert pg.execute("SELECT popularity FROM catalog.media WHERE anilist_id = 2").fetchone() == (
        None,)  # fmt: skip


def test_anilist_novels_are_excluded(ing_settings, pg):
    from tsuzuku_pipeline.ingestion import anilist_client

    assert anilist_client.media_record(_title(9, format="NOVEL"), 1, 60) is None


def test_anilist_quality_fails_when_too_few_titles(ing_settings, pg):
    ing_settings["ingestion"]["anilist"]["min_share_of_expected"] = 1.0  # 5 titres sur 6 attendus
    with pytest.raises(IngestionError, match="AniList"):
        _run_anilist(ing_settings, pg)
