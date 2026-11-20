import pytest

from tests.conftest import GENRES, write_drop, write_reco

pytestmark = pytest.mark.db

# Port fermé : la base est injoignable (connexion refusée tout de suite).
DOWN_URL = "postgresql://x:y@127.0.0.1:1/z"


def test_health_ok_with_db_and_models(client):
    body = client.get("/health").json()
    assert body == {"status": "ok", "database": "ok", "models": {"reco": "ok", "drop": "ok"}}
    assert client.get("/health/ready").status_code == 200


def test_missing_models_degrade_but_api_starts(make_client, tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    client = make_client(models=empty)
    body = client.get("/health").json()
    assert body["status"] == "degraded"
    assert body["models"] == {"reco": "unavailable", "drop": "unavailable"}
    assert client.get("/health/ready").status_code == 503
    # Les routes qui en dépendent répondent 503, pas 500.
    assert client.post("/demo/recommendations", json={"liked": []}).status_code == 503
    assert client.post("/demo/drop-risk", json={"media_id": 1}).status_code == 503


def test_failed_parity_check_refuses_reco_model(make_client, models_dir):
    # Fiche cohérente (sha256 OK) mais top de référence faux : le modèle ne doit pas être servi.
    write_reco(models_dir, parity_check={"anime_ids": [1, 2], "scores": [8.0, 8.0],
                                         "expected_top10": [8, 7, 6]})  # fmt: skip
    client = make_client(models=models_dir)
    assert client.get("/health").json()["models"]["reco"] == "unavailable"


def test_incomplete_cards_are_refused_at_startup(make_client, models_dir):
    write_reco(models_dir, relevant_min_score=None)
    card = (models_dir / "reco_model.json").read_text()
    (models_dir / "reco_model.json").write_text(card.replace('"relevant_min_score": null, ', ""))
    write_drop(models_dir, without=("threshold",))
    models = make_client(models=models_dir).get("/health").json()["models"]
    assert models == {"reco": "unavailable", "drop": "unavailable"}


def test_drop_pickle_not_matching_card_is_refused(make_client, models_dir):
    write_drop(models_dir, genres=[*GENRES, "Comedy"])  # fiche : 3 genres, pickle : 2
    assert make_client(models=models_dir).get("/health").json()["models"]["drop"] == "unavailable"


def test_corrupted_pickle_does_not_crash_startup(make_client, models_dir):
    from tsuzuku_ml.artifacts import drop_paths, sha256_file

    model_path, card_path = drop_paths(models_dir)
    model_path.write_bytes(b"pas un pickle")
    # sha256 recalculé : le fichier passe le contrôle d'intégrité mais ne se désérialise pas.
    card_path.write_text(card_path.read_text().replace(
        card_path.read_text().split('"artifact_sha256": "')[1].split('"')[0],
        sha256_file(model_path)))  # fmt: skip
    assert make_client(models=models_dir).get("/health").json()["models"]["drop"] == "unavailable"


def test_database_down_gives_503_not_500(make_client):
    client = make_client(database_url=DOWN_URL)
    assert client.get("/health").json()["database"] == "unavailable"
    resp = client.get("/media/search", params={"q": "anime"})
    assert resp.status_code == 503 and resp.json() == {"detail": "Base de données indisponible"}
    # La saison en cours reste servie, seulement sans lien vers le catalogue.
    trending = client.get("/trending")
    assert trending.status_code == 200
    assert all(i["media_id"] is None for i in trending.json()["items"])
