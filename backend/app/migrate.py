"""Migration de production (phase 11) : `python -m app.migrate`, lancé en Cloud Run Job par le
déploiement AVANT la nouvelle version de l'API.

1. Schéma du pipeline (catalog, mart) : SQL idempotent, propriété du pipeline (ADR 003). L'API
   en lit des colonnes (cover_color, media_embedding…) : il doit exister avant elle (ADR 012).
2. Migrations Alembic du schéma app.
Les fichiers SQL sont ceux du pipeline, copiés tels quels dans l'image (une seule source).
"""

import logging
import os
from pathlib import Path

import psycopg
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory

from app.core.config import REPO_ROOT, Settings

logger = logging.getLogger("tsuzuku_api.migrate")

BACKEND_DIR = Path(__file__).resolve().parents[1]
SCHEMA_ORDER = ("schema_catalog.sql", "schema_mart.sql")  # mart référence catalog


def _schema_dir() -> Path:
    default = REPO_ROOT / "pipeline" / "src" / "tsuzuku_pipeline" / "db"
    return Path(os.environ.get("PIPELINE_SCHEMA_DIR") or default)


def schema_files() -> list[Path]:
    return [_schema_dir() / name for name in SCHEMA_ORDER]


def _alembic_config(url: str) -> Config:
    # Image Docker : app est installé dans le venv, alembic.ini est ailleurs (ALEMBIC_CONFIG).
    cfg = Config(os.environ.get("ALEMBIC_CONFIG") or str(BACKEND_DIR / "alembic.ini"))
    cfg.attributes["database_url"] = url
    return cfg


def alembic_head() -> str:
    return ScriptDirectory.from_config(_alembic_config("")).get_current_head()


def run(url: str) -> None:
    psycopg_url = url.replace("postgresql+psycopg://", "postgresql://")
    with psycopg.connect(psycopg_url) as conn, conn.transaction():
        # Pas d'attente infinie derrière un verrou (une requête longue de l'ancienne API).
        conn.execute("SET LOCAL lock_timeout = '30s'")
        for path in schema_files():
            conn.execute(path.read_text(encoding="utf-8"))
    logger.info("Schéma du pipeline appliqué")
    command.upgrade(_alembic_config(url), "head")
    logger.info("Migrations Alembic à jour (%s)", alembic_head())


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    run(Settings().database_url)
