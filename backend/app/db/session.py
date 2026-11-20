"""Connexion à Postgres (SQLAlchemy 2, psycopg 3).

L'API ne fait que LIRE les schémas catalog et mart : ils appartiennent au pipeline (ADR 003),
qui les crée et les remplit. Alembic (phase 7) ne gérera que le schéma app.
Sessions synchrones : FastAPI exécute les routes `def` dans un pool de threads ; à ce volume,
c'est plus simple à écrire et à tester que l'asynchrone, sans coût mesurable.
"""

from collections.abc import Iterator

from fastapi import Request
from sqlalchemy import Engine, create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker


def make_engine(database_url: str) -> Engine:
    url = make_url(database_url)
    if url.drivername in ("postgresql", "postgres"):
        # Le .env du projet est au format libpq (postgresql://) : on précise le pilote psycopg 3.
        url = url.set(drivername="postgresql+psycopg")
    # pool_pre_ping : une connexion coupée (base redémarrée) est détectée et remplacée.
    return create_engine(url, pool_pre_ping=True, connect_args={"connect_timeout": 5})


def make_sessionmaker(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(engine, expire_on_commit=False)


def get_session(request: Request) -> Iterator[Session]:
    """Dépendance FastAPI : une session par requête, fermée à la fin."""
    with request.app.state.sessionmaker() as session:
        yield session
