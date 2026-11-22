"""Onboarding, recommandations et risque de drop calculés depuis la liste en base (phase 7)."""

import pytest

from tests.conftest import register

pytestmark = [pytest.mark.db, pytest.mark.usefixtures("clean_users")]


@pytest.fixture
def reco_client(make_client, catalog):
    # Le catalogue de test n'a que 8 animes : minimum d'onboarding abaissé à 5 pour ces tests.
    client = make_client(onboarding_min_choices=5)
    assert register(client).status_code == 201
    return client


def _onboard(client, catalog, mals):
    return client.post("/me/onboarding",
                       json={"media_ids": [catalog["anime"][m] for m in mals]})  # fmt: skip


# --- Onboarding ----------------------------------------------------------------------------------
def test_onboarding_requires_the_configured_minimum(user_client, catalog):
    # Règle réelle (settings.yaml) : 10 œuvres. 9 → refusé.
    ids = [*catalog["anime"].values(), catalog["manga"]]
    r = user_client.post("/me/onboarding", json={"media_ids": ids})
    assert r.status_code == 422 and "10" in r.json()["detail"]


@pytest.mark.parametrize("media_ids", [
    "duplicate",
    "unknown",
])  # fmt: skip
def test_onboarding_rejects_bad_ids(reco_client, catalog, media_ids):
    ids = [catalog["anime"][m] for m in (1, 2, 3, 4, 5)]
    ids = [*ids, ids[0]] if media_ids == "duplicate" else [*ids, 987654]
    assert reco_client.post("/me/onboarding", json={"media_ids": ids}).status_code == 422


def test_onboarding_replaces_previous_choices(reco_client, catalog):
    assert _onboard(reco_client, catalog, [1, 2, 3, 4, 5]).status_code == 200
    r = _onboard(reco_client, catalog, [4, 5, 6, 7, 8])
    assert r.status_code == 200 and r.json()["count"] == 5
    assert reco_client.get("/me").json()["onboarding_done"] is True
    export = reco_client.get("/me/export").json()
    assert {c["media_id"] for c in export["onboarding"]} == {
        catalog["anime"][m] for m in (4, 5, 6, 7, 8)
    }


# --- Recommandations -----------------------------------------------------------------------------
def test_new_account_gets_popularity(reco_client):
    body = reco_client.get("/me/recommendations").json()
    assert body["strategy"] == "popularity" and body["reason"].startswith("0 anime")


def test_onboarding_choices_drive_als(reco_client, catalog):
    _onboard(reco_client, catalog, [5, 6, 7, 1, 2])
    body = reco_client.get("/me/recommendations", params={"k": 3}).json()
    assert body["strategy"] == "als" and body["liked_used"] == 5
    assert body["items"][0]["media"]["title"] == "Anime 8"


def test_whole_list_is_excluded_from_recommendations(reco_client, catalog):
    _onboard(reco_client, catalog, [5, 6, 7, 1, 2])
    # Anime 8 déjà prévu (sans note) : jamais recommandé, même s'il est le meilleur candidat.
    reco_client.put(f"/me/list/{catalog['anime'][8]}", json={"status": "planning"})
    titles = [i["media"]["title"] for i in reco_client.get("/me/recommendations").json()["items"]]
    assert "Anime 8" not in titles and titles


def test_scored_list_entries_count_as_liked(reco_client, catalog):
    for mal in (5, 6, 7, 1, 2):
        reco_client.put(f"/me/list/{catalog['anime'][mal]}",
                        json={"status": "completed", "score": 9})  # fmt: skip
    body = reco_client.get("/me/recommendations").json()
    assert body["strategy"] == "als" and body["liked_used"] == 5


def test_list_score_overrides_onboarding_default(reco_client, catalog):
    _onboard(reco_client, catalog, [5, 6, 7, 1, 2])
    # Vu et détesté après l'onboarding : ne compte plus comme aimé → 4 aimés, popularité.
    reco_client.put(f"/me/list/{catalog['anime'][5]}", json={"status": "dropped", "score": 2})
    body = reco_client.get("/me/recommendations").json()
    assert body["strategy"] == "popularity" and body["reason"].startswith("4 anime")


# --- Risque de drop ------------------------------------------------------------------------------
def test_drop_risk_uses_the_stored_list(reco_client, catalog):
    for mal, status in ((2, "completed"), (3, "dropped"), (4, "completed"), (1, "in_progress")):
        reco_client.put(f"/me/list/{catalog['anime'][mal]}", json={"status": status})
    body = reco_client.get(f"/me/drop-risk/{catalog['anime'][1]}").json()
    assert body["status"] == "ok" and 0 <= body["probability"] <= 1
    # L'œuvre visée est retirée de ses propres features (3 autres entrées utilisées).
    assert body["entries_used"] == 3 and body["critical_episode"] == 3


def test_drop_risk_for_manga_is_not_a_number(reco_client, catalog):
    body = reco_client.get(f"/me/drop-risk/{catalog['manga']}").json()
    assert body["status"] == "insufficient_data" and body["probability"] is None


def test_drop_risk_unknown_media_is_404(reco_client):
    assert reco_client.get("/me/drop-risk/987654").status_code == 404


@pytest.mark.parametrize("path", ["/me/recommendations", "/me/drop-risk/1"])
def test_personal_routes_require_a_session(make_client, path):
    assert make_client().get(path).status_code == 401


def test_double_onboarding_does_not_crash(reco_client, catalog):
    """Double clic : deux onboardings simultanés. Le verrou du compte les fait passer l'un après
    l'autre (revue : le second finissait en 500 sur la clé primaire)."""
    from concurrent.futures import ThreadPoolExecutor

    ids = [catalog["anime"][m] for m in (1, 2, 3, 4, 5)]
    with ThreadPoolExecutor(max_workers=4) as pool:
        statuses = list(pool.map(
            lambda _: reco_client.post("/me/onboarding", json={"media_ids": ids}).status_code,
            range(4),
        ))  # fmt: skip
    assert statuses == [200] * 4
    assert len(reco_client.get("/me/export").json()["onboarding"]) == 5
