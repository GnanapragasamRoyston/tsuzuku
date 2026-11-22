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


# --- Populaires (phase 8 : accueil et onboarding) ----------------------------------------------
@pytest.fixture
def unranked(pg_url, catalog):
    """Anime au rang 0 : « non classé » chez MAL (œuvre pas encore sortie en 2020)."""
    import psycopg

    with psycopg.connect(pg_url, autocommit=True) as conn:
        mid = conn.execute(
            "INSERT INTO catalog.media (kind, mal_id, title, popularity, data_source)"
            " VALUES ('anime', 90000, 'Anime non classé', 0, 'mal_kaggle_2020') RETURNING id"
        ).fetchone()[0]
    yield mid
    with psycopg.connect(pg_url, autocommit=True) as conn:
        conn.execute("DELETE FROM catalog.media WHERE id = %s", (mid,))


def test_popular_sorted_by_rank_without_unranked(client, unranked):
    body = client.get("/media/popular", params={"kind": "anime", "limit": 3}).json()
    assert [i["title"] for i in body["items"]] == ["Anime 8", "Anime 7", "Anime 6"]
    titles = [i["title"] for i in client.get("/media/popular", params={"kind": "anime"}).json()[
        "items"]]  # fmt: skip
    # Rang 0 ou inconnu : jamais présenté comme populaire.
    assert "Anime non classé" not in titles and "Saison 2026" not in titles


def test_popular_paginates(client):
    first = client.get("/media/popular", params={"kind": "anime", "limit": 3}).json()["items"]
    nxt = client.get("/media/popular",
                     params={"kind": "anime", "limit": 3, "offset": 3}).json()["items"]  # fmt: skip
    assert not {i["id"] for i in first} & {i["id"] for i in nxt}
    assert [i["title"] for i in nxt] == ["Anime 5", "Anime 4", "Anime 3"]


def test_popular_accepts_several_kinds(client, pg_url, catalog):
    import psycopg

    with psycopg.connect(pg_url, autocommit=True) as conn:
        ids = [conn.execute(
            "INSERT INTO catalog.media (kind, title, popularity, data_source)"
            " VALUES (%s, %s, %s, 'anilist') RETURNING id", (k, t, r)).fetchone()[0]
            for k, t, r in (("manhwa", "Manhwa A", 2), ("manga", "Manga B", 1))]  # fmt: skip
    try:
        body = client.get("/media/popular", params=[("kind", "manga"), ("kind", "manhwa")]).json()
        assert [i["title"] for i in body["items"]] == ["Manga B", "Manhwa A"]
    finally:
        with psycopg.connect(pg_url, autocommit=True) as conn:
            conn.execute("DELETE FROM catalog.media WHERE id = ANY(%s)", (ids,))


def test_search_puts_unranked_titles_last(client, unranked):
    items = client.get("/media/search", params={"q": "anime"}).json()["items"]
    assert items[0]["title"] == "Anime 8" and items[-1]["title"] in {"Anime non classé",
                                                                     "Saison 2026"}  # fmt: skip


@pytest.mark.parametrize("params", [{}, {"kind": "film"}, {"kind": "anime", "limit": 0},
                                    {"kind": "anime", "offset": -1}])  # fmt: skip
def test_popular_rejects_invalid_input(client, params):
    assert client.get("/media/popular", params=params).status_code == 422


def test_popular_limit_is_capped(client):
    # Au-delà du maximum (settings.yaml) : plafonné, pas d'erreur.
    assert client.get("/media/popular", params={"kind": "anime", "limit": 1000}).status_code == 200


def test_search_accepts_several_kinds(client, pg_url, catalog):
    """Onglet « Manhwas et manhuas » : la recherche doit trouver les deux types."""
    import psycopg

    with psycopg.connect(pg_url, autocommit=True) as conn:
        ids = [conn.execute(
            "INSERT INTO catalog.media (kind, title, popularity, data_source)"
            " VALUES (%s, %s, 1, 'anilist') RETURNING id", (k, f"Titre {k}")).fetchone()[0]
            for k in ("manhwa", "manhua")]  # fmt: skip
    try:
        params = [("q", "Titre"), ("kind", "manhwa"), ("kind", "manhua")]
        kinds = {i["kind"] for i in client.get("/media/search", params=params).json()["items"]}
        assert kinds == {"manhwa", "manhua"}
    finally:
        with psycopg.connect(pg_url, autocommit=True) as conn:
            conn.execute("DELETE FROM catalog.media WHERE id = ANY(%s)", (ids,))


def test_media_detail_serves_the_latest_jikan_snapshot(client, catalog, pg_url):
    import psycopg

    mid = catalog["anime"][1]
    assert client.get(f"/media/{mid}").json()["latest_stats"] is None  # Jikan en panne : rien
    with psycopg.connect(pg_url, autocommit=True) as conn:
        for day, members in (("2026-11-01", 100), ("2026-11-02", 150)):
            conn.execute(
                "INSERT INTO catalog.media_daily_stats (snapshot_date, media_id, score, members,"
                " source, in_season) VALUES (%s, %s, 8.1, %s, 'jikan', true)",
                (day, mid, members),
            )
    try:
        stats = client.get(f"/media/{mid}").json()["latest_stats"]
        assert stats == {"snapshot_date": "2026-11-02", "score": 8.1, "members": 150}
    finally:
        with psycopg.connect(pg_url, autocommit=True) as conn:
            conn.execute("DELETE FROM catalog.media_daily_stats")
