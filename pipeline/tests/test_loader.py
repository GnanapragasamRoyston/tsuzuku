"""Chargement Postgres, sur une vraie base de test (tsuzuku_test), jamais sur la base de dev."""

import logging

import psycopg
import pytest

from tsuzuku_pipeline.db import loader

pytestmark = pytest.mark.db

MEDIA = [
    # kind, mal_id, title, title_alt, synopsis, episodes, format, duration_min, start_year,
    # creators, source, age_rating, popularity
    ("anime", 1, "Cowboy Bebop", "Cowboy Bebop", "Space.", 26, "TV", 24.0, 1998, ["Sunrise"],
     "Original", "R - 17+", 39),
    ("anime", 5, "Film", None, None, 1, "Movie", 115.0, 2001, [], None, None, 518),
]  # fmt: skip
GENRES = [(1, "Action"), (1, "Sci-Fi"), (5, "Action")]


def _ids(conn):
    return dict(conn.execute("SELECT mal_id, id FROM catalog.media").fetchall())


def test_apply_schemas_is_idempotent(pg):
    loader.apply_schemas(pg)
    loader.apply_schemas(pg)
    tables = {
        r[0]
        for r in pg.execute(
            "SELECT table_schema || '.' || table_name FROM information_schema.tables"
            " WHERE table_schema IN ('catalog', 'mart')"
        )
    }
    assert {"catalog.media", "catalog.genre", "catalog.media_genre", "mart.drop_curve",
            "mart.critical_episode", "mart.retention_by_genre",
            "mart.retention_by_studio"} <= tables  # fmt: skip


def test_upsert_media_inserts_rows_and_genres(pg):
    assert loader.upsert_media(pg, MEDIA, GENRES) == 2
    title, creators = pg.execute(
        "SELECT title, creators FROM catalog.media WHERE mal_id = 1"
    ).fetchone()
    assert (title, creators) == ("Cowboy Bebop", ["Sunrise"])
    genres = pg.execute(
        "SELECT m.mal_id, g.name FROM catalog.media_genre mg"
        " JOIN catalog.media m ON m.id = mg.media_id JOIN catalog.genre g ON g.id = mg.genre_id"
        " ORDER BY 1, 2"
    ).fetchall()
    assert genres == GENRES


def test_second_upsert_keeps_ids_and_updates_values(pg):
    loader.upsert_media(pg, MEDIA, GENRES)
    before = _ids(pg)
    changed = [("anime", 1, "Cowboy Bebop (édité)", *MEDIA[0][3:]), MEDIA[1]]
    loader.upsert_media(pg, changed, [(1, "Action")])
    assert _ids(pg) == before  # les futures listes utilisateurs pointent sur ces ids
    assert pg.execute("SELECT title FROM catalog.media WHERE mal_id = 1").fetchone()[0] == (
        "Cowboy Bebop (édité)"
    )
    # Les genres de l'œuvre sont remplacés, pas accumulés.
    n = pg.execute(
        "SELECT count(*) FROM catalog.media_genre mg JOIN catalog.media m ON m.id = mg.media_id"
        " WHERE m.mal_id = 1"
    ).fetchone()[0]
    assert n == 1


def test_replace_media_mart_maps_mal_id_to_media_id(pg):
    loader.upsert_media(pg, MEDIA, GENRES)
    ids = _ids(pg)
    loader.replace_mart(pg, "drop_curve", [(1, 0, 3, 0.5), (1, 2, 3, 1.0)])
    rows = pg.execute(
        "SELECT media_id, episode, nb_drops FROM mart.drop_curve ORDER BY 2"
    ).fetchall()
    assert rows == [(ids[1], 0, 3), (ids[1], 2, 3)]


def test_replace_mart_replaces_previous_content(pg):
    loader.upsert_media(pg, MEDIA, GENRES)
    loader.replace_mart(pg, "drop_curve", [(1, 0, 3, 0.5), (1, 2, 3, 1.0)])
    loader.replace_mart(pg, "drop_curve", [(5, 1, 1, 1.0)])
    assert pg.execute("SELECT count(*) FROM mart.drop_curve").fetchone()[0] == 1


def test_replace_mart_is_atomic_on_error(pg):
    loader.upsert_media(pg, MEDIA, GENRES)
    loader.replace_mart(pg, "drop_curve", [(1, 0, 3, 0.5)])
    # mal_id 999 absent du catalogue : tout le remplacement doit être annulé.
    with pytest.raises(loader.LoaderError, match="999|absent"):
        loader.replace_mart(pg, "drop_curve", [(5, 1, 1, 1.0), (999, 1, 1, 1.0)])
    assert pg.execute("SELECT count(*) FROM mart.drop_curve").fetchone()[0] == 1


def test_replace_mart_check_constraint_rolls_back(pg):
    loader.upsert_media(pg, MEDIA, GENRES)
    loader.replace_mart(pg, "drop_curve", [(1, 0, 3, 0.5)])
    with pytest.raises(psycopg.errors.CheckViolation):
        loader.replace_mart(pg, "drop_curve", [(1, 1, 3, 1.5)])  # part cumulée > 1
    assert pg.execute("SELECT count(*) FROM mart.drop_curve").fetchone()[0] == 1


def test_replace_group_mart(pg):
    loader.replace_mart(pg, "retention_by_genre", [("Action", 2, 3, 3, 0.5, 0.43, 0.25)])
    row = pg.execute("SELECT genre, nb_anime FROM mart.retention_by_genre").fetchone()
    assert row == ("Action", 2)


def test_unknown_mart_rejected(pg):
    with pytest.raises(loader.LoaderError, match="inconnue"):
        loader.replace_mart(pg, "drop_curve; DROP TABLE x", [])


def test_replace_mart_fails_fast_when_table_is_locked(pg, pg_url):
    loader.upsert_media(pg, MEDIA, GENRES)
    loader.replace_mart(pg, "drop_curve", [(1, 0, 3, 0.5)])
    # Une autre session lit la table et garde sa transaction ouverte (ex. outil BI).
    with psycopg.connect(pg_url) as reader:
        reader.execute("SELECT count(*) FROM mart.drop_curve").fetchone()
        with pytest.raises(loader.LoaderError, match="verrouillée"):
            loader.replace_mart(pg, "drop_curve", [(5, 1, 1, 1.0)], lock_timeout="300ms")
        reader.rollback()
    assert pg.execute("SELECT count(*) FROM mart.drop_curve").fetchone()[0] == 1


def test_upsert_removes_media_gone_from_same_source_only(pg):
    loader.upsert_media(pg, MEDIA, GENRES)
    # Une œuvre ajoutée par une autre source (ex. Jikan, phase 6) ne doit pas être touchée.
    loader.upsert_media(
        pg, [("anime", 77, "Récent", *MEDIA[1][3:])], [(77, "Action")], data_source="jikan"
    )
    # Anime 5 sort de la source Kaggle (ex. nouvellement classé adulte).
    loader.upsert_media(pg, [MEDIA[0]], [(1, "Action")])
    left = dict(pg.execute("SELECT mal_id, data_source FROM catalog.media").fetchall())
    assert left == {1: "mal_kaggle_2020", 77: "jikan"}
    orphans = pg.execute(
        "SELECT count(*) FROM catalog.media_genre mg"
        " LEFT JOIN catalog.media m ON m.id = mg.media_id WHERE m.id IS NULL"
    ).fetchone()[0]
    assert orphans == 0  # genres de l'œuvre retirée supprimés en cascade


def test_full_load_in_one_transaction(pg):
    # Comme _build_load : catalogue + plusieurs marts dans UNE transaction englobante.
    with pg.transaction():
        loader.upsert_media(pg, MEDIA, GENRES)
        loader.replace_mart(pg, "drop_curve", [(1, 0, 3, 1.0)])
        loader.replace_mart(
            pg, "critical_episode", [(1, 2, 0.5, 0.4, 3, 5, 6, 0.45)]
        )  # 2e mart par œuvre : tmp_mart doit avoir été supprimée
    assert pg.execute("SELECT count(*) FROM mart.critical_episode").fetchone()[0] == 1


def test_failure_mid_load_rolls_back_everything(pg):
    with pg.transaction():
        loader.upsert_media(pg, MEDIA, GENRES)
        loader.replace_mart(pg, "drop_curve", [(1, 0, 3, 1.0)])
    with pytest.raises(loader.LoaderError), pg.transaction():
        loader.replace_mart(pg, "drop_curve", [(5, 1, 1, 1.0)])  # réussirait seul...
        loader.replace_mart(pg, "critical_episode", [(999, 2, 0.5, 0.4, 3, 5, 6, 0.45)])
    # ... mais l'échec du mart suivant annule aussi le premier : pas de mélange de versions.
    rows = pg.execute("SELECT episode FROM mart.drop_curve").fetchall()
    assert rows == [(0,)]


def test_apply_schemas_does_not_wait_for_readers(pg, pg_url):
    # Une session (API, Power BI) lit les tables et garde sa transaction ouverte. Rejouer le DDL
    # ne doit prendre aucun verrou exclusif : il passe sans attendre (sinon LockNotAvailable).
    with psycopg.connect(pg_url) as reader:
        reader.execute("SELECT count(*) FROM mart.critical_episode").fetchone()
        reader.execute("SELECT count(*) FROM catalog.media").fetchone()
        loader.apply_schemas(pg, lock_timeout="300ms")
        reader.rollback()


def test_schema_upgrade_fails_fast_when_readers_hold_the_table(pg, pg_url):
    # Base « ancienne version » : la colonne ajoutée plus tard manque, donc le DDL doit faire un
    # vrai ALTER TABLE (verrou exclusif). Un lecteur resté ouvert ne doit pas le bloquer à vie.
    pg.execute("ALTER TABLE mart.critical_episode DROP COLUMN initial_drop_risk")
    with psycopg.connect(pg_url) as reader:
        reader.execute("SELECT count(*) FROM mart.critical_episode").fetchone()
        with pytest.raises(psycopg.errors.LockNotAvailable):
            loader.apply_schemas(pg, lock_timeout="300ms")
        reader.rollback()
    loader.apply_schemas(pg)  # lecteur parti : la mise à niveau passe
    cols = {
        r[0]
        for r in pg.execute(
            "SELECT column_name FROM information_schema.columns"
            " WHERE table_schema = 'mart' AND table_name = 'critical_episode'"
        )
    }
    assert "initial_drop_risk" in cols


@pytest.mark.parametrize(
    "url", ["postgresql:/user:s3cr3t@localhost:5433/db", "host=x password=s3cr3t port=abc"]
)
def test_malformed_url_never_leaks_password(url, caplog):
    assert "s3cr3t" not in loader.describe(url)
    with caplog.at_level(logging.DEBUG), pytest.raises(loader.LoaderError) as exc:
        loader.connect(url)
    assert "s3cr3t" not in str(exc.value)
    assert "s3cr3t" not in caplog.text


RUN = {
    "run_id": "6f1c1d2e-0000-4000-8000-000000000001",
    "created_at": "2026-11-16T12:00:00Z",
    "model_name": "drop",
    "model_type": "hgb",
    "params": {"learning_rate": 0.1},
    "metrics": {"test": {"pr_auc": 0.3}},
    "data_fingerprint": "abc",
    "artifact": "models/drop_model.joblib",
}


def test_insert_model_run_is_append_only_and_idempotent(pg):
    assert loader.insert_model_run(pg, RUN) is True
    assert loader.insert_model_run(pg, RUN) is False  # même run_id : pas de doublon
    loader.insert_model_run(pg, {**RUN, "run_id": "6f1c1d2e-0000-4000-8000-000000000002"})
    rows = pg.execute(
        "SELECT model_type, metrics->'test'->>'pr_auc' FROM mart.model_runs ORDER BY run_id"
    ).fetchall()
    assert rows == [("hgb", "0.3"), ("hgb", "0.3")]


def test_insert_model_run_rejects_incomplete(pg):
    with pytest.raises(loader.LoaderError, match="data_fingerprint"):
        loader.insert_model_run(pg, {k: v for k, v in RUN.items() if k != "data_fingerprint"})


def test_describe_hides_password():
    url = "postgresql://user:s3cr3t@db.example:5433/tsuzuku"
    assert loader.describe(url) == "db.example:5433/tsuzuku"


def test_connect_error_hides_password(caplog):
    url = "postgresql://user:s3cr3t@127.0.0.1:1/nope?connect_timeout=1"
    with caplog.at_level(logging.DEBUG), pytest.raises(loader.LoaderError) as exc:
        loader.connect(url)
    assert "s3cr3t" not in str(exc.value)
    assert "s3cr3t" not in caplog.text
    assert exc.value.__cause__ is None
