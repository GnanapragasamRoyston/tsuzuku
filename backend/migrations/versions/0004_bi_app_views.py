"""Vues Power BI de l'activité des comptes (phase 13, ADR 016, SPEC § 11 page 6).

Schéma bi : Power BI ne lit que des vues, jamais app.*. Ces vues sont AGRÉGÉES et ANONYMES :
- aucune colonne d'identité (user_id, email, pseudo) ni de texte libre (critiques) ;
- aucune ligne calculée sur moins de MIN_GROUP_SIZE comptes (sinon elle est masquée) : avec peu de
  comptes, un compteur ou une médiane décrirait une personne précise.
Les vues sur catalog et mart sont dans pipeline/.../views_powerbi.sql (propriété du pipeline).

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-28
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Recopié de config/settings.yaml (powerbi.min_group_size) : une vue ne lit pas ce fichier.
# backend/tests/test_bi.py vérifie le comportement avec la valeur de settings.yaml.
MIN_GROUP_SIZE = 5
# Seule valeur insérée dans le SQL ci-dessous : un entier constant, jamais une entrée extérieure
# (d'où les noqa S608, « injection SQL possible », sans objet ici).
K = int(MIN_GROUP_SIZE)

VIEWS = {
    # Totaux : une seule ligne, masquée tant qu'il y a moins de k comptes. Seulement des nombres
    # de COMPTES : un total d'entrées, moins les statuts affichés par app_status_counts, donnerait
    # par soustraction le nombre d'entrées d'un statut masqué, donc d'une seule personne
    # (revue de la phase 13).
    "app_totals": f"""
        SELECT t.nb_accounts, t.nb_onboarded
        FROM (
            SELECT (SELECT count(*) FROM app.users) AS nb_accounts,
                   (SELECT count(DISTINCT user_id) FROM app.onboarding_choice) AS nb_onboarded
        ) t
        WHERE t.nb_accounts >= {K}""",  # noqa: S608
    # Inscriptions par semaine (lundi), semaines de moins de k inscriptions masquées.
    "app_signups_weekly": f"""
        SELECT date_trunc('week', created_at)::date AS week, count(*) AS nb_signups
        FROM app.users
        GROUP BY 1
        HAVING count(*) >= {K}""",  # noqa: S608
    "app_status_counts": f"""
        SELECT status, count(*) AS nb_entries, count(DISTINCT user_id) AS nb_accounts
        FROM app.list_entry
        GROUP BY status
        HAVING count(DISTINCT user_id) >= {K}""",  # noqa: S608
    # Œuvres les plus ajoutées (tous statuts).
    "app_top_added": f"""
        SELECT m.id AS media_id, m.title, m.kind, count(DISTINCT e.user_id) AS nb_accounts
        FROM app.list_entry e
        JOIN catalog.media m ON m.id = e.media_id
        GROUP BY m.id, m.title, m.kind
        HAVING count(DISTINCT e.user_id) >= {K}""",  # noqa: S608
    # Drops déclarés dans Tsuzuku, face à l'épisode critique mesuré sur MyAnimeList (mart).
    "app_declared_drops": f"""
        SELECT m.id AS media_id, m.title, m.kind,
               count(DISTINCT e.user_id) AS nb_accounts,
               percentile_cont(0.5) WITHIN GROUP (ORDER BY e.dropped_at) AS median_dropped_at,
               c.critical_episode
        FROM app.list_entry e
        JOIN catalog.media m ON m.id = e.media_id
        LEFT JOIN mart.critical_episode c ON c.media_id = m.id
        WHERE e.status = 'dropped'
        GROUP BY m.id, m.title, m.kind, c.critical_episode
        HAVING count(DISTINCT e.user_id) >= {K}""",  # noqa: S608
}


def upgrade() -> None:
    # Le schéma bi est créé par views_powerbi.sql (appliqué avant Alembic) ; IF NOT EXISTS pour
    # une base où seul Alembic tourne (service api-migrate en local).
    op.execute("CREATE SCHEMA IF NOT EXISTS bi")
    for name, query in VIEWS.items():
        op.execute(f"CREATE OR REPLACE VIEW bi.{name} AS {query}")


def downgrade() -> None:
    for name in VIEWS:
        op.execute(f"DROP VIEW IF EXISTS bi.{name}")
