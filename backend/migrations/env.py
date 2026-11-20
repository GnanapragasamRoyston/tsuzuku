"""Environnement Alembic : migrations du schéma app UNIQUEMENT.

catalog et mart appartiennent au pipeline (fichiers SQL, ADR 003) : les filtres include_name et
include_object empêchent Alembic de les comparer, donc de proposer un jour de les modifier ou
de les supprimer.
La table de suivi des versions vit elle aussi dans app.
"""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import text

from app.core.config import get_settings
from app.db import app_models  # noqa: F401  (enregistre les tables app dans Base.metadata)
from app.db.models import Base
from app.db.session import make_engine

SCHEMA = app_models.SCHEMA
config = context.config
if config.config_file_name is not None and config.attributes.get("configure_logger", True):
    fileConfig(config.config_file_name, disable_existing_loggers=False)


def run_migrations_online() -> None:
    # Les tests passent l'URL de leur base ; sinon, DATABASE_URL (.env ou environnement).
    url = config.attributes.get("database_url") or get_settings().database_url
    engine = make_engine(url)
    with engine.connect() as connection:
        # Les tables app ont des FK vers catalog.media, créé par le pipeline : sans lui, message
        # clair plutôt que « relation does not exist » au milieu de la migration.
        if connection.execute(text("SELECT to_regclass('catalog.media')")).scalar() is None:
            raise SystemExit(
                "Table catalog.media absente : charge d'abord le catalogue (make spark), "
                "puis relance les migrations."
            )
        # La table de version vit dans app : le schéma doit exister AVANT la 1re migration (créé
        # par infra/postgres/init en local, mais pas sur une base neuve de test ou chez Neon).
        connection.execute(text(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}"))
        # Commit AVANT context.configure, et plus aucune requête ensuite : une transaction déjà
        # ouverte serait prise pour une transaction « externe », et Alembic ne validerait jamais
        # la migration (tables créées puis annulées en silence).
        connection.commit()
        context.configure(
            connection=connection,
            target_metadata=Base.metadata,
            include_schemas=True,
            include_name=app_models.alembic_include_name,
            include_object=app_models.alembic_include_object,
            version_table_schema=SCHEMA,
            compare_type=True,
            compare_server_default=True,
        )
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


if context.is_offline_mode():
    raise SystemExit("Mode hors ligne non pris en charge : lance les migrations sur une base.")
run_migrations_online()
