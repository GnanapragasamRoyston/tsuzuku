import datetime as dt

import psycopg
import pytest

from tests.conftest import FakeJikan

pytestmark = pytest.mark.db


@pytest.fixture
def snapshot(pg_url, catalog):
    """Snapshot quotidien en base (comme l'écrit le DAG jikan_daily_ingest)."""

    def write(day):
        with psycopg.connect(pg_url, autocommit=True) as conn:
            conn.execute("DELETE FROM catalog.media_daily_stats")
            # Anime 4 : dans le snapshot mais via la watchlist (hors saison) → pas dans /trending.
            for mal, members, in_season in ((2, 500, True), (3, 900, True), (4, 9999, False)):
                conn.execute(
                    "INSERT INTO catalog.media_daily_stats (snapshot_date, media_id, score,"
                    " members, source, in_season) VALUES (%s, %s, 8.0, %s, 'jikan', %s)",
                    (day, catalog["anime"][mal], members, in_season),
                )

    yield write
    with psycopg.connect(pg_url, autocommit=True) as conn:
        conn.execute("DELETE FROM catalog.media_daily_stats")


def test_recent_snapshot_is_served_from_database_without_calling_jikan(make_client, snapshot):
    snapshot(dt.datetime.now(dt.UTC).date())
    fake = FakeJikan()
    body = make_client(transport=fake).get("/trending").json()
    assert body["origin"] == "database" and fake.calls == 0
    assert [i["title"] for i in body["items"]] == ["Anime 3", "Anime 2"]  # membres décroissants
    assert all(i["media_id"] is not None for i in body["items"])


def test_old_snapshot_falls_back_to_live_jikan(make_client, snapshot):
    snapshot(dt.datetime.now(dt.UTC).date() - dt.timedelta(days=10))
    fake = FakeJikan()
    body = make_client(transport=fake).get("/trending").json()
    assert body["origin"] == "live" and fake.calls == 1


def test_live_trending_links_catalog_and_sorts_by_members(client, catalog):
    body = client.get("/trending").json()
    assert body["origin"] == "live"
    assert [i["mal_id"] for i in body["items"]] == [999, 1]  # 50 membres, puis 10 ; adulte filtré
    linked = {i["mal_id"]: i["media_id"] for i in body["items"]}
    assert linked == {999: None, 1: catalog["anime"][1]}
    assert body["items"][1]["cover_url"] == "http://img/1" and body["stale"] is False


def test_missing_table_falls_back_to_live_jikan(make_client, pg_url):
    # Base où ni make spark ni le DAG n'ont tourné : la table n'existe pas (ProgrammingError).
    with psycopg.connect(pg_url, autocommit=True) as conn:
        conn.execute("ALTER TABLE catalog.media_daily_stats RENAME TO media_daily_stats_off")
    try:
        body = make_client().get("/trending").json()
        assert body["origin"] == "live"
    finally:
        with psycopg.connect(pg_url, autocommit=True) as conn:
            conn.execute("ALTER TABLE catalog.media_daily_stats_off RENAME TO media_daily_stats")


def test_trending_503_when_jikan_down_and_no_snapshot(make_client):
    client = make_client(transport=FakeJikan(statuses=[503] * 10))
    resp = client.get("/trending")
    assert resp.status_code == 503 and "Jikan" in resp.json()["detail"]
