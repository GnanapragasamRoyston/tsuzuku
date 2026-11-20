import pytest

pytestmark = pytest.mark.db


def _liked(catalog, mals, score=None):
    return [{"media_id": catalog["anime"][m], **({"score": score} if score else {})} for m in mals]


def test_recommendations_use_als_from_five_liked(client, catalog):
    body = client.post("/demo/recommendations",
                       json={"liked": _liked(catalog, [5, 6, 7, 1, 2]), "k": 3}).json()  # fmt: skip
    assert body["strategy"] == "als" and body["liked_used"] == 5
    titles = [i["media"]["title"] for i in body["items"]]
    # Profil surtout « groupe 5-8 » : les recos viennent de ce groupe, jamais d'un titre déjà aimé.
    assert titles[0] == "Anime 8"
    assert not {"Anime 5", "Anime 6", "Anime 7", "Anime 1", "Anime 2"} & set(titles)
    assert body["items"][0]["because"] in {"Anime 5", "Anime 6", "Anime 7"}


def test_under_five_liked_serves_popularity(client, catalog):
    body = client.post("/demo/recommendations",
                       json={"liked": _liked(catalog, [1, 2]), "k": 3}).json()  # fmt: skip
    assert body["strategy"] == "popularity" and "au moins 5" in body["reason"]
    # Popularité de la fiche (8, 7, 6, …), sans les titres déjà aimés.
    assert [i["media"]["title"] for i in body["items"]] == ["Anime 8", "Anime 7", "Anime 6"]


def test_non_anime_and_unknown_titles_are_reported_as_ignored(client, catalog):
    liked = [*_liked(catalog, [1, 2, 3, 4, 5]), {"media_id": catalog["manga"]},
             {"media_id": 987654}]  # fmt: skip
    body = client.post("/demo/recommendations", json={"liked": liked}).json()
    assert body["strategy"] == "als"
    assert set(body["liked_ignored"]) == {catalog["manga"], 987654}


def test_low_scores_do_not_count_as_liked(client, catalog):
    # 5 titres connus, mais tous notés 3 : aucun n'est « aimé » → popularité.
    payload = {"liked": _liked(catalog, [1, 2, 3, 4, 5], score=3)}
    body = client.post("/demo/recommendations", json=payload).json()
    assert body["strategy"] == "popularity" and body["reason"].startswith("0 anime")


def test_one_liked_and_four_disliked_is_not_enough(client, catalog):
    # Revue : la règle des 5 comptait aussi les titres non aimés. 1 aimé (9) + 4 détestés (2).
    liked = [*_liked(catalog, [5], score=9), *_liked(catalog, [1, 2, 3, 4], score=2)]
    body = client.post("/demo/recommendations", json={"liked": liked}).json()
    assert body["strategy"] == "popularity" and body["reason"].startswith("1 anime")


def test_because_never_cites_a_disliked_title(client, catalog):
    liked = [*_liked(catalog, [5, 6, 7, 8], score=9), *_liked(catalog, [1], score=10),
             *_liked(catalog, [2, 3], score=1)]  # fmt: skip
    body = client.post("/demo/recommendations", json={"liked": liked}).json()
    assert body["strategy"] == "als" and body["liked_used"] == 5
    assert {i["because"] for i in body["items"]} <= {"Anime 5", "Anime 6", "Anime 7", "Anime 8",
                                                     "Anime 1"}  # fmt: skip


@pytest.mark.parametrize("payload", [
    {"liked": [{"media_id": 0}]},
    {"liked": [{"media_id": 1, "score": 11}]},
    {"liked": [], "k": 0},
    {"liked": [{"media_id": i} for i in range(1, 502)]},
])  # fmt: skip
def test_recommendations_reject_invalid_input(client, payload):
    assert client.post("/demo/recommendations", json=payload).status_code == 422


def test_k_is_capped(client, catalog):
    body = client.post("/demo/recommendations", json={"liked": [], "k": 1000}).json()
    assert len(body["items"]) <= 50


def test_drop_risk_for_anime(client, catalog):
    entries = [{"media_id": catalog["anime"][m], "status": s}
               for m, s in ((2, "dropped"), (3, "completed"), (4, "in_progress"))]  # fmt: skip
    payload = {"media_id": catalog["anime"][1], "entries": entries}
    body = client.post("/demo/drop-risk", json=payload).json()
    assert body["status"] == "ok"
    assert 0 <= body["probability"] <= 1 and body["threshold"] == 0.5
    assert body["at_risk"] == (body["probability"] >= 0.5)
    assert body["entries_used"] == 3
    assert body["critical_episode"] == 3 and body["point_of_no_return"] == 5


def test_drop_risk_ignores_target_in_its_own_list(client, catalog):
    target = catalog["anime"][1]
    body = client.post("/demo/drop-risk", json={
        "media_id": target, "entries": [{"media_id": target, "status": "dropped"}],
    }).json()  # fmt: skip
    assert body["entries_used"] == 0  # leave-one-out : la cible ne compte pas pour elle-même


def test_drop_risk_manga_has_no_invented_number(client, catalog):
    body = client.post("/demo/drop-risk", json={"media_id": catalog["manga"]}).json()
    assert body["status"] == "insufficient_data"
    assert body["probability"] is None and "Pas encore assez" in body["message"]


def test_drop_risk_recent_anime_has_no_invented_number(client, catalog):
    # Revue : un anime ajouté par Jikan avait des features vides mais recevait un chiffre.
    body = client.post("/demo/drop-risk", json={"media_id": catalog["recent"]}).json()
    assert body["status"] == "insufficient_data" and body["probability"] is None
    assert "2020" in body["message"]


def test_drop_risk_rejects_duplicate_entries(client, catalog):
    a2 = catalog["anime"][2]
    entries = [{"media_id": a2, "status": "dropped"}, {"media_id": a2, "status": "completed"}]
    payload = {"media_id": catalog["anime"][1], "entries": entries}
    resp = client.post("/demo/drop-risk", json=payload)
    assert resp.status_code == 422 and "plusieurs fois" in resp.text


def test_drop_risk_errors(client):
    assert client.post("/demo/drop-risk", json={"media_id": 987654}).status_code == 404
    bad = {"media_id": 1, "entries": [{"media_id": 2, "status": "watching"}]}
    assert client.post("/demo/drop-risk", json=bad).status_code == 422
