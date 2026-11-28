"""Migration de production (phase 11) : `python -m app.migrate`, lancé en Cloud Run Job par le
déploiement AVANT la nouvelle version de l'API.

1. Schéma du pipeline (catalog, mart) : SQL idempotent, propriété du pipeline (ADR 003). L'API
   en lit des colonnes (cover_color, media_embedding…) : il doit exister avant elle (ADR 012).
2. Migrations Alembic du schéma app.
Les fichiers SQL sont ceux du pipeline, copiés tels quels dans l'image (une seule source).
"""

import hashlib
import logging
import os
import re
from pathlib import Path

import psycopg
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from psycopg import sql

from app.core.config import REPO_ROOT, Settings

logger = logging.getLogger("tsuzuku_api.migrate")

BACKEND_DIR = Path(__file__).resolve().parents[1]
SCHEMA_ORDER = ("schema_catalog.sql", "schema_mart.sql")  # mart référence catalog
# Vues Power BI (phase 13, ADR 016) sur catalog et mart, puis vues bi sur app par Alembic (0004).
# Réappliquées seulement si le fichier a changé ou si une vue manque : CREATE OR REPLACE VIEW
# pose un verrou exclusif même sans changement, et un déploiement pendant un rafraîchissement
# Power BI échouerait. Même règle que pipeline/.../db/loader.py (apply_views), recopiée ici :
# l'image de l'API n'embarque pas le paquet du pipeline.
VIEWS_FILE = "views_powerbi.sql"
VIEWS_MARKER = "views_powerbi sha256:"


def _schema_dir() -> Path:
    default = REPO_ROOT / "pipeline" / "src" / "tsuzuku_pipeline" / "db"
    return Path(os.environ.get("PIPELINE_SCHEMA_DIR") or default)


def schema_files() -> list[Path]:
    return [_schema_dir() / name for name in SCHEMA_ORDER]


def apply_views(conn: psycopg.Connection, text: str) -> bool:
    """Applique les vues bi si le fichier a changé (empreinte gardée en commentaire du schéma bi)
    ou si l'une d'elles manque ; sinon ne fait rien. Renvoie True si elles ont été appliquées."""
    marker = VIEWS_MARKER + hashlib.sha256(text.encode("utf-8")).hexdigest()
    names = re.findall(r"CREATE OR REPLACE VIEW bi\.(\w+)", text)
    current = conn.execute(
        "SELECT obj_description(oid, 'pg_namespace') FROM pg_namespace WHERE nspname = 'bi'"
    ).fetchone()
    present = conn.execute(
        "SELECT count(*) FROM pg_views WHERE schemaname = 'bi' AND viewname = ANY(%s)", (names,)
    ).fetchone()[0]
    if current and current[0] == marker and present == len(names):
        return False
    conn.execute(text)
    conn.execute(sql.SQL("COMMENT ON SCHEMA bi IS {}").format(sql.Literal(marker)))
    return True


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
        if apply_views(conn, (_schema_dir() / VIEWS_FILE).read_text(encoding="utf-8")):
            logger.info("Vues Power BI (schéma bi) appliquées")
    logger.info("Schéma du pipeline appliqué")
    command.upgrade(_alembic_config(url), "head")
    logger.info("Migrations Alembic à jour (%s)", alembic_head())


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    run(Settings().database_url)
