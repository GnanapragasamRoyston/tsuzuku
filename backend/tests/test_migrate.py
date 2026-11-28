"""Job de migration de production (phase 11, ADR 012 et 014) : schéma du pipeline (catalog, mart)
PUIS migrations Alembic (app), lancé par le déploiement AVANT la nouvelle API."""

import psycopg
import pytest

from app import migrate

pytestmark = pytest.mark.db


def test_migrate_is_idempotent_and_reaches_the_alembic_head(pg_url, catalog):
    migrate.run(pg_url)
    migrate.run(pg_url)  # rejouable : un redéploiement ne casse rien
    with psycopg.connect(pg_url) as conn:
        version = conn.execute("SELECT version_num FROM app.alembic_version").fetchone()[0]
        columns = {r[0] for r in conn.execute(
            "SELECT column_name FROM information_schema.columns"
            " WHERE table_schema = 'catalog' AND table_name = 'media'"
        )}  # fmt: skip
        has_embeddings = conn.execute(
            "SELECT to_regclass('catalog.media_embedding') IS NOT NULL"
        ).fetchone()[0]
    assert version == migrate.alembic_head()
    # Colonnes du pipeline que l'API lit (ADR 012) : présentes avant qu'elle ne démarre.
    assert {"cover_source", "cover_color"} <= columns and has_embeddings


def test_schema_files_come_in_dependency_order():
    assert [p.name for p in migrate.schema_files()] == ["schema_catalog.sql", "schema_mart.sql"]


def test_a_redeploy_never_waits_for_a_power_bi_refresh(pg_url, catalog):
    """Vues inchangées : le job de migration ne les réapplique pas, donc ne demande aucun verrou
    sur une vue qu'un rafraîchissement Power BI est en train de lire (revue de la phase 13)."""
    migrate.run(pg_url)
    with psycopg.connect(pg_url) as reader, psycopg.connect(pg_url) as conn:
        reader.execute("SELECT count(*) FROM bi.anime_drop").fetchone()  # transaction ouverte
        conn.execute("SET lock_timeout = '300ms'")
        text = (migrate._schema_dir() / migrate.VIEWS_FILE).read_text(encoding="utf-8")
        assert migrate.apply_views(conn, text) is False
