import pytest

from tests.conftest import FakeJikan

pytestmark = pytest.mark.db


def test_trending_links_catalog_and_sorts_by_members(client, catalog):
    body = client.get("/trending").json()
    assert [i["mal_id"] for i in body["items"]] == [999, 1]  # 50 membres, puis 10 ; adulte filtré
    linked = {i["mal_id"]: i["media_id"] for i in body["items"]}
    assert linked == {999: None, 1: catalog["anime"][1]}
    assert body["items"][1]["cover_url"] == "http://img/1" and body["stale"] is False


def test_trending_503_when_jikan_down_and_no_cache(make_client):
    client = make_client(transport=FakeJikan(statuses=[503] * 10))
    resp = client.get("/trending")
    assert resp.status_code == 503 and "Jikan" in resp.json()["detail"]
