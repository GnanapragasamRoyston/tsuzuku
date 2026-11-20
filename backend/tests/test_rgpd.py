"""RGPD : export des données et suppression du compte (SPEC § 7)."""

import psycopg
import pytest

from tests.conftest import PASSWORD

pytestmark = [pytest.mark.db, pytest.mark.usefixtures("clean_users")]


def _fill(client, catalog):
    client.put(
        f"/me/list/{catalog['anime'][1]}",
        json={"status": "dropped", "progress": 3, "score": 4, "review": "trop lent"},
    )
    client.put(f"/me/list/{catalog['manga']}", json={"status": "in_progress", "progress": 12})


def test_export_contains_all_personal_data(user_client, catalog):
    _fill(user_client, catalog)
    r = user_client.get("/me/export")
    assert r.status_code == 200
    assert "attachment" in r.headers["content-disposition"]
    data = r.json()
    assert data["user"]["pseudo"] == "royston" and data["user"]["email"] == "royston@example.com"
    assert "password" not in r.text and "argon2" not in r.text and "token_version" not in r.text
    entries = {e["media_id"]: e for e in data["list"]}
    assert entries[catalog["anime"][1]]["review"] == "trop lent"
    assert entries[catalog["anime"][1]]["title"] == "Anime 1"
    assert entries[catalog["manga"]]["progress"] == 12
    assert data["onboarding"] == [] and "exported_at" in data


def test_delete_account_requires_password(user_client):
    r = user_client.request("DELETE", "/me", json={"password": "mauvais-mdp"})
    assert r.status_code == 403
    assert user_client.get("/me").status_code == 200


def test_delete_account_erases_everything(user_client, catalog, pg_url, make_client):
    _fill(user_client, catalog)
    r = user_client.request("DELETE", "/me", json={"password": PASSWORD})
    assert r.status_code == 204
    assert user_client.get("/me").status_code == 401
    with psycopg.connect(pg_url) as conn:
        counts = [conn.execute(f"SELECT count(*) FROM app.{t}").fetchone()[0]  # noqa: S608
                  for t in ("users", "list_entry", "onboarding_choice")]  # fmt: skip
        media = conn.execute("SELECT count(*) FROM catalog.media").fetchone()[0]
    assert counts == [0, 0, 0]
    assert media == len(catalog["anime"]) + 2  # le catalogue, lui, n'est pas touché
    login = make_client().post(
        "/auth/login", json={"email": "royston@example.com", "password": PASSWORD}
    )
    assert login.status_code == 401


def test_catalog_removal_cascades_to_lists(user_client, catalog, pg_url):
    """Le pipeline retire parfois une œuvre (absente de la source) : l'entrée suit, sans erreur."""
    with psycopg.connect(pg_url, autocommit=True) as conn:
        extra = conn.execute(
            "INSERT INTO catalog.media (kind, title, data_source) VALUES ('manga', 'Éphémère',"
            " 'anilist') RETURNING id"
        ).fetchone()[0]
    user_client.put(f"/me/list/{extra}", json={"status": "planning"})
    with psycopg.connect(pg_url, autocommit=True) as conn:
        conn.execute("DELETE FROM catalog.media WHERE id = %s", (extra,))
    assert user_client.get("/me/list").json()["total"] == 0


def test_delete_account_password_attempts_are_limited(user_client):
    """Un cookie volé ne permet pas de deviner le mot de passe sans limite via DELETE /me."""
    for _ in range(5):
        r = user_client.request("DELETE", "/me", json={"password": "mauvais-mdp"})
        assert r.status_code == 403
    r = user_client.request("DELETE", "/me", json={"password": PASSWORD})
    assert r.status_code == 429 and int(r.headers["Retry-After"]) > 0
    assert user_client.get("/me").status_code == 200
