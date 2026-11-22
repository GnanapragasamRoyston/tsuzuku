"""Migrations Alembic du schéma app."""

import psycopg
import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import CheckConstraint

from app.db import app_models
from app.db.models import Base
from app.db.session import make_engine
from tests.conftest import alembic_config

pytestmark = pytest.mark.db

# Définition complète des tables du pipeline (colonnes, types, défauts, contraintes) : une
# migration de l'API ne doit jamais la changer.
PIPELINE_SCHEMA = """
SELECT 'col', table_schema, table_name, column_name, data_type, column_default, is_nullable
FROM information_schema.columns WHERE table_schema IN ('catalog', 'mart')
UNION ALL
SELECT 'con', n.nspname, c.conrelid::regclass::text, c.conname, pg_get_constraintdef(c.oid),
       NULL, NULL
FROM pg_constraint c JOIN pg_namespace n ON n.oid = c.connamespace
WHERE n.nspname IN ('catalog', 'mart')
ORDER BY 1, 2, 3, 4
"""


def _app_tables(url) -> set[str]:
    with psycopg.connect(url) as conn:
        rows = conn.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = 'app'"
        ).fetchall()
    return {r[0] for r in rows}


def test_models_match_migrations(pg_url):
    """Modèles SQLAlchemy et migrations décrivent le même schéma (colonnes, types, défauts,
    index, FK) : sinon, un changement de modèle a été oublié dans une migration."""
    engine = make_engine(pg_url)
    with engine.connect() as conn:
        ctx = MigrationContext.configure(conn, opts={
            "include_schemas": True,
            "include_name": app_models.alembic_include_name,
            "include_object": app_models.alembic_include_object,
            "compare_type": True,
            "compare_server_default": True,
            "version_table_schema": app_models.SCHEMA,  # même réglage qu'env.py
        })  # fmt: skip
        diff = compare_metadata(ctx, Base.metadata)
    engine.dispose()
    assert diff == []


def test_check_constraints_match_models(pg_url):
    """compare_metadata ignore les CHECK : on les compare à part (nom et présence)."""
    expected = {
        c.name
        for t in Base.metadata.tables.values() if t.schema == app_models.SCHEMA
        for c in t.constraints if isinstance(c, CheckConstraint)
    }  # fmt: skip
    with psycopg.connect(pg_url) as conn:
        found = {
            r[0]
            for r in conn.execute(
                "SELECT conname FROM pg_constraint c JOIN pg_namespace n"
                " ON n.oid = c.connamespace WHERE n.nspname = 'app' AND c.contype = 'c'"
            )
        }
    assert found == expected and len(expected) == 8  # dont cover_suggestion_status (lot qualité)


def test_migrations_go_down_and_up_without_touching_pipeline_schemas(pg_url, clean_users):
    with psycopg.connect(pg_url) as conn:
        before = conn.execute(PIPELINE_SCHEMA).fetchall()
    cfg = alembic_config(pg_url)
    command.downgrade(cfg, "base")
    assert _app_tables(pg_url) == {"alembic_version"}
    command.upgrade(cfg, "head")
    assert {"users", "list_entry", "onboarding_choice"} <= _app_tables(pg_url)
    with psycopg.connect(pg_url) as conn:
        after = conn.execute(PIPELINE_SCHEMA).fetchall()
    assert before and before == after


def test_migration_refuses_a_database_without_catalog(pg_url):
    """Base neuve sans catalogue : arrêt avec un message clair, rien de créé."""
    from sqlalchemy.engine import make_url

    from tests.conftest import _base_url

    name = f"{make_url(pg_url).database}_empty"
    base = _base_url()
    with psycopg.connect(base, autocommit=True) as admin:
        admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
        admin.execute(f'CREATE DATABASE "{name}"')
    try:
        url = make_url(pg_url).set(database=name).render_as_string(hide_password=False)
        with pytest.raises(SystemExit, match="make spark"):
            command.upgrade(alembic_config(url), "head")
        assert _app_tables(url) == set()
    finally:
        with psycopg.connect(base, autocommit=True) as admin:
            admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
