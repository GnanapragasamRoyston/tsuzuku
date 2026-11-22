"""« Proposer une jaquette » : URL d'image des seuls domaines autorisés, file de modération
(app.cover_suggestion), validation par Royston en ligne de commande (lot qualité des jaquettes)."""

import psycopg
import pytest
from scripts import covers_review

from tests.conftest import register

pytestmark = [pytest.mark.db, pytest.mark.usefixtures("clean_users")]

ANILIST = "https://s4.anilist.co/file/anilistcdn/media/anime/cover/large/bx1-abc.jpg"
MAL = "https://cdn.myanimelist.net/images/anime/4/19644l.jpg"
KITSU = "https://media.kitsu.app/anime/poster_images/1/large.jpg"


def _suggest(client, media_id, url):
    return client.post(f"/media/{media_id}/cover-suggestions", json={"url": url})


@pytest.mark.parametrize("url", [ANILIST, MAL, KITSU])
def test_allowed_hosts_are_queued(user_client, catalog, url):
    r = _suggest(user_client, catalog["anime"][1], url)
    assert r.status_code == 201 and r.json() == {"status": "pending"}


@pytest.mark.parametrize("url", [
    "http://s4.anilist.co/file/anilistcdn/x.jpg",  # pas de HTTPS
    "https://evil.example/x.jpg",  # hôte non autorisé
    "https://s4.anilist.co.evil.example/file/anilistcdn/x.jpg",  # faux sous-domaine
    "https://user@cdn.myanimelist.net/images/x.jpg",  # identifiants dans l'URL
    "https://cdn.myanimelist.net:8443/images/x.jpg",  # port
    "https://cdn.myanimelist.net/profile/x.jpg",  # bon hôte, mauvais chemin
    "https://media.kitsu.app/anime/poster_images/1/large.jpg?x=1",  # paramètres
    "https://cdn.myanimelist.net/images/../admin",  # remontée de dossier
    "https://cdn.myanimelist.net/images/%2e%2e/profile/x.jpg",  # remontée de dossier encodée
    "javascript:alert(1)",
    "https://cdn.myanimelist.net/images/" + "a" * 600,  # trop long
])  # fmt: skip
def test_untrusted_urls_are_refused(user_client, catalog, url):
    r = _suggest(user_client, catalog["anime"][1], url)
    assert r.status_code == 422


def test_requires_a_session_and_an_existing_media(make_client, user_client, catalog):
    assert _suggest(make_client(), catalog["anime"][1], ANILIST).status_code == 401
    assert _suggest(user_client, 999_999, ANILIST).status_code == 404


def test_same_url_twice_is_a_conflict(user_client, catalog):
    assert _suggest(user_client, catalog["anime"][1], MAL).status_code == 201
    assert _suggest(user_client, catalog["anime"][1], MAL).status_code == 409


def test_daily_limit(make_client, catalog):
    client = make_client(cover_suggestions_per_day=2)
    assert register(client).status_code == 201
    for i in (1, 2):
        assert _suggest(client, catalog["anime"][i], MAL).status_code == 201
    assert _suggest(client, catalog["anime"][3], MAL).status_code == 429


def test_suggestions_are_in_the_export_and_deleted_with_the_account(user_client, catalog, pg_url):
    _suggest(user_client, catalog["anime"][1], MAL)
    export = user_client.get("/me/export").json()
    assert export["cover_suggestions"][0]["url"] == MAL
    assert export["cover_suggestions"][0]["status"] == "pending"
    user_client.request("DELETE", "/me", json={"password": "un-mot-de-passe-solide"})
    with psycopg.connect(pg_url) as conn:
        assert conn.execute("SELECT count(*) FROM app.cover_suggestion").fetchone() == (0,)


# --- Modération par Royston (scripts/covers_review.py) -------------------------------------------
@pytest.fixture
def media_cover(pg_url, catalog):
    mid = catalog["anime"][2]

    def read():
        with psycopg.connect(pg_url) as conn:
            return conn.execute(
                "SELECT cover_url, cover_source FROM catalog.media WHERE id = %s", (mid,)
            ).fetchone()

    yield mid, read
    with psycopg.connect(pg_url, autocommit=True) as conn:
        conn.execute("UPDATE catalog.media SET cover_url = NULL, cover_source = NULL,"
                     " cover_color = NULL WHERE id = %s", (mid,))  # fmt: skip


def test_approve_sets_the_cover_and_reject_does_not(user_client, pg_url, media_cover):
    mid, read = media_cover
    _suggest(user_client, mid, MAL)
    _suggest(user_client, mid, KITSU)
    pending = covers_review.pending(pg_url)
    assert [p["url"] for p in pending] == [MAL, KITSU]
    covers_review.reject(pg_url, pending[1]["id"])
    assert read() == (None, None)
    covers_review.approve(pg_url, pending[0]["id"])
    assert read() == (MAL, "suggestion")
    assert covers_review.pending(pg_url) == []
    # Une proposition déjà traitée ne se traite pas deux fois.
    with pytest.raises(covers_review.NotPending):
        covers_review.approve(pg_url, pending[1]["id"])


def test_review_listing_never_shows_emails(user_client, pg_url, catalog):
    _suggest(user_client, catalog["anime"][1], MAL)
    assert "example.com" not in repr(covers_review.pending(pg_url))


def test_other_users_suggestions_are_independent(make_client, user_client, catalog):
    other = make_client()
    assert register(other, pseudo="autre").status_code == 201
    assert _suggest(user_client, catalog["anime"][1], MAL).status_code == 201
    assert _suggest(other, catalog["anime"][1], MAL).status_code == 201


def test_resubmitting_at_the_limit_says_already_suggested(make_client, catalog):
    client = make_client(cover_suggestions_per_day=1)
    assert register(client).status_code == 201
    assert _suggest(client, catalog["anime"][1], MAL).status_code == 201
    # La même image : « déjà proposée » (409), pas « trop de propositions » (429).
    assert _suggest(client, catalog["anime"][1], MAL).status_code == 409
