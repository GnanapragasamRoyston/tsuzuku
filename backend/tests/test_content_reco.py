"""Recos par le contenu (phase 10, ADR 013) : manga/manhwa/manhua, cross-média, « même esprit ».

Embeddings écrits à la main en base (pas de modèle) : axe 0 = « action », axe 1 = « drame ».
Animes 1-4 = action, 5-8 = drame (catalogue de conftest).
"""

import psycopg
import pytest

from tests.conftest import register

pytestmark = [pytest.mark.db, pytest.mark.usefixtures("clean_users")]

DIM = 384


def _vec(action: float, drama: float, noise: float = 0.0) -> str:
    v = [0.0] * DIM
    v[0], v[1], v[2] = action, drama, noise
    norm = sum(x * x for x in v) ** 0.5
    return "[" + ",".join(str(x / norm) for x in v) + "]"


@pytest.fixture(scope="module")
def books(pg_url, catalog):
    """Manhwas, manhua et embeddings ; tout est retiré à la fin du module."""
    with psycopg.connect(pg_url, autocommit=True) as conn:

        def add(kind, title, popularity):
            return conn.execute(
                "INSERT INTO catalog.media (kind, title, popularity, data_source)"
                " VALUES (%s, %s, %s, 'anilist') RETURNING id", (kind, title, popularity),
            ).fetchone()[0]  # fmt: skip

        ids = {
            "manhwa_action": add("manhwa", "Manhwa action", 3),
            "manhwa_drame": add("manhwa", "Manhwa drame", 1),
            "manhua_action": add("manhua", "Manhua action", 2),
            "manhwa_sans": add("manhwa", "Manhwa sans embedding", 4),
        }
        vectors = {catalog["anime"][m]: _vec(1, 0, 0.01 * m) for m in (1, 2, 3, 4)}
        vectors |= {catalog["anime"][m]: _vec(0, 1, 0.01 * m) for m in (5, 6, 7, 8)}
        vectors |= {
            ids["manhwa_action"]: _vec(0.95, 0.05),
            ids["manhwa_drame"]: _vec(0.05, 0.95),
            ids["manhua_action"]: _vec(0.9, 0.1),
            catalog["manga"]: _vec(0.5, 0.5),
        }
        for mid, v in vectors.items():
            conn.execute(
                "INSERT INTO catalog.media_embedding (media_id, model, text_hash, embedding)"
                " VALUES (%s, 'test', 'h', %s::vector)", (mid, v),
            )  # fmt: skip
    yield ids
    with psycopg.connect(pg_url, autocommit=True) as conn:
        conn.execute("DELETE FROM catalog.media_embedding")
        conn.execute("DELETE FROM catalog.media WHERE id = ANY(%s)", (list(ids.values()),))


def _rate(client, media_id, score, status="completed"):
    r = client.put(f"/me/list/{media_id}", json={"status": status, "score": score})
    assert r.status_code == 200, r.text


def _recos(client, *kinds):
    return client.get("/me/recommendations", params=[("kind", k) for k in kinds])


# --- /me/recommendations par le contenu ----------------------------------------------------------
def test_action_fan_gets_the_action_manhwa_with_a_cross_media_reason(user_client, catalog, books):
    _rate(user_client, catalog["anime"][1], 9)
    _rate(user_client, catalog["anime"][2], 10)
    r = _recos(user_client, "manhwa")
    assert r.status_code == 200
    body = r.json()
    assert body["strategy"] == "content"
    titles = [i["media"]["title"] for i in body["items"]]
    assert titles[0] == "Manhwa action" and "Manhwa drame" in titles
    assert "Manhwa sans embedding" not in titles  # pas de vecteur : pas classable
    assert body["items"][0]["because"] in ("Anime 1", "Anime 2")  # cross-média
    assert all(i["media"]["kind"] == "manhwa" for i in body["items"])


def test_several_kinds_and_already_listed_works_are_excluded(user_client, catalog, books):
    _rate(user_client, catalog["anime"][1], 9)
    _rate(user_client, books["manhwa_action"], None, status="planning")  # déjà dans la liste
    titles = [i["media"]["title"] for i in _recos(user_client, "manhwa", "manhua").json()["items"]]
    assert titles[0] == "Manhua action" and "Manhwa action" not in titles


def test_dislikes_do_not_make_a_taste_profile(user_client, catalog, books):
    _rate(user_client, catalog["anime"][1], 3)  # note sous le neutre : pas un goût
    body = _recos(user_client, "manhwa").json()
    assert body["strategy"] == "popularity"
    assert [i["media"]["title"] for i in body["items"]][0] == "Manhwa drame"  # le plus populaire


def test_onboarding_choices_count_as_likes(user_client, catalog, books):
    ids = [catalog["anime"][m] for m in (5, 6, 7, 8)] + [catalog["anime"][m] for m in (1, 2)]
    ids += [catalog["anime"][m] for m in (3, 4)] + [catalog["manga"], books["manhwa_sans"]]
    assert user_client.post("/me/onboarding", json={"media_ids": ids}).status_code == 200
    body = _recos(user_client, "manhua").json()
    assert body["strategy"] == "content" and body["items"][0]["media"]["title"] == "Manhua action"


def test_anime_stays_als_and_mixing_anime_with_books_is_refused(user_client, books):
    assert _recos(user_client, "anime").json()["strategy"] in ("als", "popularity")
    assert _recos(user_client, "anime", "manhwa").status_code == 422


def test_requires_a_session(make_client, books):
    assert _recos(make_client(), "manhwa").status_code == 401


def test_popularity_weight_lifts_known_works(make_client, catalog, books):
    """Hybride (ADR 013) : β = 0 → le plus proche ; β très grand → le plus populaire du type.
    « Manhwa drame » est le n° 1 de popularité, « Manhwa action » le plus proche d'un fan
    d'action."""
    for beta, first in ((0.0, "Manhwa action"), (50.0, "Manhwa drame")):
        client = make_client(content_popularity_beta=beta)
        assert register(client, pseudo=f"beta_{int(beta)}").status_code == 201
        _rate(client, catalog["anime"][1], 10)
        assert _recos(client, "manhwa").json()["items"][0]["media"]["title"] == first


def test_scores_follow_the_order_and_ignored_lists_only_unusable_likes(user_client, catalog, books):
    _rate(user_client, catalog["anime"][1], 10)
    _rate(user_client, catalog["anime"][5], 2)  # mal noté : pas un goût, mais pas « ignoré »
    _rate(user_client, books["manhwa_sans"], 9)  # aimé mais sans embedding : ignoré
    body = _recos(user_client, "manga", "manhua").json()
    scores = [i["score"] for i in body["items"]]
    assert scores == sorted(scores, reverse=True)  # score hybride, dans l'ordre servi
    assert body["liked_ignored"] == [books["manhwa_sans"]]


def test_book_recos_do_not_need_the_als_model(make_client, catalog, books, tmp_path):
    client = make_client(models=tmp_path)  # aucun artefact ALS
    assert register(client, pseudo="sans_als").status_code == 201
    _rate(client, catalog["anime"][1], 10)
    assert _recos(client, "manhwa").status_code == 200
    assert _recos(client, "anime").status_code == 503  # l'ALS, lui, manque bien


# --- /media/{id}/similar -------------------------------------------------------------------------
def test_similar_works_across_types_without_itself(client, catalog, books):
    r = client.get(f"/media/{catalog['anime'][1]}/similar", params={"k": 4})
    assert r.status_code == 200
    titles = [m["title"] for m in r.json()["items"]]
    assert "Anime 1" not in titles and len(titles) == 4
    assert {"Anime 2", "Manhwa action"} <= set(titles)  # cross-média : anime → manhwa
    assert "Manhwa drame" not in titles


def test_unranked_works_do_not_break_the_hybrid_score(client, pg_url, catalog, books):
    """Popularité 0 = « non classé » chez MAL : ln(1 + 0) = 0, la division plantait (500)."""
    with psycopg.connect(pg_url, autocommit=True) as conn:
        conn.execute("UPDATE catalog.media SET popularity = 0 WHERE id = %s",
                     (books["manhwa_action"],))  # fmt: skip
    try:
        r = client.get(f"/media/{catalog['anime'][1]}/similar", params={"k": 10})
        assert r.status_code == 200 and "Manhwa action" in [m["title"] for m in r.json()["items"]]
    finally:
        with psycopg.connect(pg_url, autocommit=True) as conn:
            conn.execute("UPDATE catalog.media SET popularity = 3 WHERE id = %s",
                         (books["manhwa_action"],))  # fmt: skip


def test_similar_is_empty_without_embedding_and_404_for_unknown(client, books):
    assert client.get(f"/media/{books['manhwa_sans']}/similar").json() == {"items": []}
    assert client.get("/media/999999/similar").status_code == 404


def test_similar_k_is_bounded(client, catalog, books):
    assert client.get(f"/media/{catalog['anime'][1]}/similar", params={"k": 500}).status_code == 422


def test_other_users_lists_do_not_leak(make_client, user_client, catalog, books):
    other = make_client()
    assert register(other, pseudo="autre").status_code == 201
    _rate(other, catalog["anime"][5], 10)
    _rate(user_client, catalog["anime"][1], 10)
    assert _recos(user_client, "manhwa").json()["items"][0]["media"]["title"] == "Manhwa action"
