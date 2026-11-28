"""Rôle Postgres de Power BI (phase 13, ADR 016) : `make bi-role`, ou `python -m app.bi_role`.

Le rôle tsuzuku_bi ne lit QUE les vues du schéma bi : aucun droit sur app (comptes), catalog ni
mart. Une vue s'exécute avec les droits de son propriétaire : le rôle n'a besoin que du SELECT
sur les vues. Ses sessions sont en lecture seule et bornées dans le temps.

- Rejouable : crée le rôle, ou change son mot de passe s'il existe ;
- droits par défaut : une vue AJOUTÉE plus tard par le propriétaire est lisible tout de suite
  (CREATE OR REPLACE VIEW, lui, garde les droits existants) ;
- mot de passe lu dans BI_DB_PASSWORD (.env, jamais commité), jamais affiché ni journalisé, et
  envoyé au serveur sous forme de hachage SCRAM uniquement.
"""

import logging
import os

import psycopg
from dotenv import dotenv_values
from psycopg import sql

from app.core.config import REPO_ROOT, Settings

logger = logging.getLogger("tsuzuku_api.bi_role")

ROLE = "tsuzuku_bi"
MIN_PASSWORD_LENGTH = 16
# Un rafraîchissement Power BI qui traînerait ne doit pas garder Neon éveillé indéfiniment.
STATEMENT_TIMEOUT = "120s"


def ensure(conn: psycopg.Connection, password: str, role: str = ROLE) -> None:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise ValueError(f"BI_DB_PASSWORD : {MIN_PASSWORD_LENGTH} caractères minimum")
    name = sql.Identifier(role)
    exists = conn.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (role,)).fetchone()
    # Mot de passe passé en littéral SQL échappé par psycopg (jamais concaténé, jamais affiché).
    # Haché en SCRAM-SHA-256 CÔTÉ CLIENT : seul le hachage part vers le serveur, donc un journal
    # de requêtes (DDL tracé, erreur, pg_stat_statements) ne contient jamais le mot de passe.
    hashed = conn.pgconn.encrypt_password(password.encode(), role.encode(), b"scram-sha-256")
    verb = sql.SQL("ALTER" if exists else "CREATE")
    create = sql.SQL("{} ROLE {} WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD {}")
    conn.execute(create.format(verb, name, sql.Literal(hashed.decode())))
    database = conn.execute("SELECT current_database()").fetchone()[0]
    for statement in (
        "ALTER ROLE {role} SET default_transaction_read_only = on",
        f"ALTER ROLE {{role}} SET statement_timeout = '{STATEMENT_TIMEOUT}'",
        "GRANT CONNECT ON DATABASE {db} TO {role}",
        "GRANT USAGE ON SCHEMA bi TO {role}",
        "GRANT SELECT ON ALL TABLES IN SCHEMA bi TO {role}",
        "ALTER DEFAULT PRIVILEGES IN SCHEMA bi GRANT SELECT ON TABLES TO {role}",
    ):
        conn.execute(sql.SQL(statement).format(role=name, db=sql.Identifier(database)))
    logger.info("Rôle %s prêt : lecture seule sur le schéma bi", role)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    # Seul BI_DB_PASSWORD est lu dans .env : charger tout le fichier écraserait le DATABASE_URL
    # passé en ligne de commande (`DATABASE_URL=<Neon> make bi-role`) par l'URL locale.
    # « or "" » : une ligne BI_DB_PASSWORD sans valeur donne None, et le message clair des
    # 16 caractères plutôt qu'une TypeError.
    password = (
        os.environ.get("BI_DB_PASSWORD") or dotenv_values(REPO_ROOT / ".env").get("BI_DB_PASSWORD")
    ) or ""
    url = Settings().database_url.replace("postgresql+psycopg://", "postgresql://")
    with psycopg.connect(url, autocommit=True) as conn:
        ensure(conn, password)


if __name__ == "__main__":
    main()
