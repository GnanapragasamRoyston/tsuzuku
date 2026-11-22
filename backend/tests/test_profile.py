"""Profil public (/users/{pseudo}), réglage de visibilité (PATCH /me), entrée seule (phase 9)."""

import pytest

from tests.conftest import register

pytestmark = [pytest.mark.db, pytest.mark.usefixtures("clean_users")]


def _put(client, media_id, **body):
    return client.put(f"/me/list/{media_id}", json={"status": "in_progress", **body})


def _go_public(client):
    r = client.patch("/me", json={"profile_public": True})
    assert r.status_code == 200
    return r


# --- Visibilité du profil ------------------------------------------------------------------------
def test_profile_is_private_by_default(user_client):
    assert user_client.get("/me").json()["profile_public"] is False


def test_patch_me_toggles_visibility(user_client):
    assert _go_public(user_client).json()["profile_public"] is True
    assert user_client.get("/me").json()["profile_public"] is True
    r = user_client.patch("/me", json={"profile_public": False})
    assert r.status_code == 200 and r.json()["profile_public"] is False


def test_patch_me_validates_input_and_requires_a_session(user_client, make_client):
    # Pas de conversion silencieuse ("oui" → True), pas de champ inconnu (pseudo, email…).
    assert user_client.patch("/me", json={"profile_public": "oui"}).status_code == 422
    assert user_client.patch("/me", json={"pseudo": "pirate"}).status_code == 422
    assert make_client().patch("/me", json={"profile_public": True}).status_code == 401


def test_export_contains_visibility(user_client):
    _go_public(user_client)
    assert user_client.get("/me/export").json()["user"]["profile_public"] is True


# --- Profil public -------------------------------------------------------------------------------
def test_private_and_unknown_profiles_give_the_same_404(user_client, make_client):
    visitor = make_client()
    private = visitor.get("/users/royston")
    unknown = visitor.get("/users/personne")
    invalid = visitor.get("/users/PAS-UN-PSEUDO")
    # Même réponse : on ne peut pas savoir si un pseudo existe (pas d'énumération des comptes).
    assert private.status_code == unknown.status_code == invalid.status_code == 404
    assert private.json() == unknown.json() == invalid.json()
    assert private.headers["cache-control"] == "no-store"


def test_public_profile_shows_stats_without_private_data(user_client, make_client, catalog):
    anime = catalog["anime"]
    _put(user_client, anime[1], status="completed", score=9)  # 12 ép., Action
    _put(user_client, anime[2], status="completed", score=7)  # 24 ép., Action
    _put(user_client, anime[5], status="dropped", progress=3, dropped_at=3)  # Drama
    _put(user_client, anime[6], status="in_progress", progress=5, review="critique perso")  # Drama
    _put(user_client, anime[7], status="planning")
    _go_public(user_client)

    r = make_client().get("/users/royston")  # visiteur sans cookie
    assert r.status_code == 200
    body = r.json()
    assert body["pseudo"] == "royston"
    assert body["counts"] == {"planning": 1, "in_progress": 1, "completed": 2, "paused": 0,
                              "dropped": 1}  # fmt: skip
    assert body["episodes_watched"] == 12 + 24 + 3 + 5
    # Taux de drop (SPEC § 5) : dropped / (dropped + completed).
    assert body["drop_rate"] == pytest.approx(1 / 3)
    # Genres des œuvres en cours ou terminées : Action ×2, Drama ×1.
    assert body["top_genres"] == ["Action", "Drama"]
    assert [(s["media"]["id"], s["score"]) for s in body["recent_scores"]] == [
        (anime[2], 7), (anime[1], 9)
    ]  # fmt: skip
    text = r.text
    assert "royston@example.com" not in text and "critique perso" not in text
    assert "email" not in body
    # Un profil repassé en privé doit disparaître tout de suite : pas de cache.
    assert r.headers["cache-control"] == "no-store"


def test_drop_rate_is_hidden_below_the_minimum(user_client, make_client, catalog):
    _put(user_client, catalog["anime"][1], status="dropped", progress=1, dropped_at=1)
    _go_public(user_client)
    body = make_client().get("/users/royston").json()
    # Une seule œuvre finie ou lâchée : « 100 % de drop » ne dirait rien. Pas de faux chiffre.
    assert body["drop_rate"] is None


def test_profile_turned_private_disappears(user_client, make_client):
    _go_public(user_client)
    visitor = make_client()
    assert visitor.get("/users/royston").status_code == 200
    user_client.patch("/me", json={"profile_public": False})
    assert visitor.get("/users/royston").status_code == 404


def test_profiles_are_isolated(user_client, make_client, catalog):
    other = make_client()
    assert register(other, pseudo="autre").status_code == 201
    _put(other, catalog["anime"][3], status="completed", score=10)
    _go_public(user_client)
    body = make_client().get("/users/royston").json()
    assert body["recent_scores"] == [] and body["episodes_watched"] == 0


# --- Entrée seule de la liste (fiche œuvre) ------------------------------------------------------
def test_get_single_entry(user_client, catalog):
    mid = catalog["anime"][3]
    assert user_client.get(f"/me/list/{mid}").status_code == 404
    _put(user_client, mid, progress=4, score=8)
    r = user_client.get(f"/me/list/{mid}")
    assert r.status_code == 200
    assert r.json()["progress"] == 4 and r.json()["score"] == 8
    assert r.json()["media"]["id"] == mid


def test_single_entry_is_scoped_to_the_account(user_client, make_client, catalog):
    mid = catalog["anime"][3]
    _put(user_client, mid)
    other = make_client()
    assert register(other, pseudo="autre").status_code == 201
    assert other.get(f"/me/list/{mid}").status_code == 404
    assert make_client().get(f"/me/list/{mid}").status_code == 401
