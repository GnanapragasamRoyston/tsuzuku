"""Visibilité du profil public (phase 9).

Privé par défaut (décision de Royston, 2026-11-22, ADR 011) : un profil n'est visible que si la
personne coche la case dans « Compte ». Les comptes existants restent donc privés.

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("profile_public", sa.Boolean(), server_default=sa.false(), nullable=False),
        schema="app",
    )


def downgrade() -> None:
    op.drop_column("users", "profile_public", schema="app")
