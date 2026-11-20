"""Liste d'un compte : /me/list (phase 7)."""

import pytest

from tests.conftest import register

pytestmark = [pytest.mark.db, pytest.mark.usefixtures("clean_users")]


def _put(client, media_id, **body):
    return client.put(f"/me/list/{media_id}", json={"status": "in_progress", **body})


def test_put_creates_then_updates_an_entry(user_client, catalog):
    mid = catalog["anime"][3]  # Anime 3 : 36 épisodes
    r = _put(user_client, mid, progress=4, score=7)
    assert r.status_code == 200
    assert r.json()["status"] == "in_progress" and r.json()["progress"] == 4
    r = _put(user_client, mid, status="paused", progress=10)
    assert r.status_code == 200 and r.json()["status"] == "paused"
    # Un PUT remplace l'entrée entière : la note non renvoyée est effacée (sémantique de PUT).
    assert r.json()["score"] is None
    items = user_client.get("/me/list").json()["items"]
    assert len(items) == 1 and items[0]["media"]["title"] == "Anime 3"


def test_list_filters_by_status_and_paginates(user_client, catalog):
    for mal in (1, 2, 3):
        _put(user_client, catalog["anime"][mal], status="planning")
    _put(user_client, catalog["anime"][4], status="dropped", progress=2)
    page = user_client.get("/me/list", params={"status": "planning", "limit": 2}).json()
    assert page["total"] == 3 and len(page["items"]) == 2
    rest = user_client.get(
        "/me/list", params={"status": "planning", "limit": 2, "offset": 2}
    ).json()
    seen = {i["media"]["id"] for i in page["items"] + rest["items"]}
    assert seen == {catalog["anime"][m] for m in (1, 2, 3)}
    assert user_client.get("/me/list", params={"limit": 1000}).status_code == 422


def test_completed_fills_progress_with_episode_count(user_client, catalog):
    r = _put(user_client, catalog["anime"][2], status="completed")  # 24 épisodes
    assert r.json()["progress"] == 24


def test_dropped_defaults_drop_point_to_progress(user_client, catalog):
    r = _put(user_client, catalog["anime"][2], status="dropped", progress=5)
    assert r.json()["dropped_at"] == 5
    r = _put(user_client, catalog["anime"][2], status="dropped", progress=5, dropped_at=3)
    assert r.json()["dropped_at"] == 3


@pytest.mark.parametrize(
    "body",
    [
        {"progress": 25},  # Anime 2 : 24 épisodes
        {"progress": -1},
        {"status": "abandonné"},
        {"status": "paused", "dropped_at": 3},  # lâché à l'épisode X, mais pas « dropped »
        {"status": "dropped", "progress": 5, "dropped_at": 30},
        {"score": 11},
        {"score": 0},
        {"review": "x" * 2001},
        {"started_at": "2026-11-10", "finished_at": "2026-11-01"},
        {"user_id": 2},  # champ inconnu : on ne choisit pas à qui appartient l'entrée
    ],
)
def test_put_validates_entries(user_client, catalog, body):
    assert _put(user_client, catalog["anime"][2], **body).status_code == 422


def test_progress_is_not_capped_when_total_is_unknown(user_client, catalog):
    # Le manga de test n'a pas de nombre de chapitres connu (série en cours) : pas de plafond.
    assert _put(user_client, catalog["manga"], progress=250).status_code == 200


def test_unknown_media_is_404(user_client):
    assert _put(user_client, 987654).status_code == 404


def test_delete_entry(user_client, catalog):
    mid = catalog["anime"][1]
    _put(user_client, mid)
    assert user_client.delete(f"/me/list/{mid}").status_code == 204
    assert user_client.delete(f"/me/list/{mid}").status_code == 404
    assert user_client.get("/me/list").json()["total"] == 0


def test_users_cannot_see_or_touch_each_other_lists(user_client, make_client, catalog):
    mid = catalog["anime"][1]
    _put(user_client, mid, score=9)
    other = make_client()
    assert register(other, pseudo="autre").status_code == 201
    assert other.get("/me/list").json()["total"] == 0
    assert other.delete(f"/me/list/{mid}").status_code == 404
    _put(other, mid, status="dropped", progress=1)
    # L'entrée du premier compte n'a pas bougé.
    entry = user_client.get("/me/list").json()["items"][0]
    assert entry["status"] == "in_progress" and entry["score"] == 9


def test_list_size_is_capped(make_client, clean_users, catalog):
    client = make_client(list_max_entries=2)
    register(client)
    for mal in (1, 2):
        assert _put(client, catalog["anime"][mal]).status_code == 200
    assert _put(client, catalog["anime"][3]).status_code == 409
    # Modifier une entrée existante reste possible à la limite.
    assert _put(client, catalog["anime"][1], status="completed").status_code == 200


@pytest.mark.parametrize(
    "call",
    [
        lambda c: c.get("/me/list"),
        lambda c: c.put("/me/list/1", json={"status": "planning"}),
        lambda c: c.delete("/me/list/1"),
    ],
)
def test_list_routes_require_a_session(make_client, call):
    assert call(make_client()).status_code == 401


def test_drop_point_cannot_exceed_progress_even_without_total(user_client, catalog):
    # Total du manga inconnu : la règle dropped_at ≤ progression s'applique quand même.
    r = _put(user_client, catalog["manga"], status="dropped", progress=5, dropped_at=30)
    assert r.status_code == 422
