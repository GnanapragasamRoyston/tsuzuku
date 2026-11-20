import pytest

pytestmark = pytest.mark.db


def test_search_by_title_and_alt_title_sorted_by_popularity(client):
    items = client.get("/media/search", params={"q": "anime"}).json()["items"]
    # Popularité = rang MAL (plus petit = plus populaire) : Anime 8 (rang 92) en tête.
    assert [i["title"] for i in items][:3] == ["Anime 8", "Anime 7", "Anime 6"]
    alt = client.get("/media/search", params={"q": "Alt 3"}).json()["items"]
    assert [i["title"] for i in alt] == ["Anime 3"]


def test_search_filters_kind_and_limits(client):
    # « Manga 1 » et aucun anime ne contient « an » ET n'est un manga : le filtre de type joue.
    items = client.get("/media/search", params={"q": "an", "kind": "manga"}).json()["items"]
    assert [i["kind"] for i in items] == ["manga"]
    assert len(client.get("/media/search", params={"q": "anime", "limit": 2}).json()["items"]) == 2


def test_search_treats_sql_wildcards_as_text(client):
    assert client.get("/media/search", params={"q": "%%"}).json()["items"] == []


INVALID_SEARCHES = [
    {"q": "a"},
    {"q": "x" * 101},
    {"q": "ab", "kind": "film"},
    {"q": "ab", "limit": 0},
    {"q": "   "},  # seulement des espaces : vide après nettoyage
    {"q": " a "},
]


@pytest.mark.parametrize("params", INVALID_SEARCHES)
def test_search_rejects_invalid_input(client, params):
    assert client.get("/media/search", params=params).status_code == 422


def test_media_detail_includes_drop_indicators(client, catalog):
    body = client.get(f"/media/{catalog['anime'][1]}").json()
    assert body["title"] == "Anime 1" and body["genres"] == ["Action"]
    assert body["critical"]["critical_episode"] == 3
    assert body["critical"]["point_of_no_return"] == 5
    assert [p["episode"] for p in body["drop_curve"]] == [1, 3, 5]


def test_media_without_indicators(client, catalog):
    body = client.get(f"/media/{catalog['anime'][2]}").json()
    assert body["critical"] is None and body["drop_curve"] == []


def test_unknown_media_is_404_and_bad_id_422(client):
    assert client.get("/media/999999").status_code == 404
    assert client.get("/media/0").status_code == 422
