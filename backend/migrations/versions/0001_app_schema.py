"""Schéma app : comptes, listes, choix d'onboarding (phase 7).

Écrite à la main (et non générée) pour relire chaque contrainte ; test_migrations.py vérifie
qu'elle correspond exactement aux modèles de app/db/app_models.py.
Prérequis : le schéma catalog existe (FK vers catalog.media), créé par le pipeline.

Revision ID: 0001
Revises:
Create Date: 2026-11-20
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

STATUSES = ("planning", "in_progress", "completed", "paused", "dropped")


def _created_at(name: str = "created_at") -> sa.Column:
    return sa.Column(name, sa.DateTime(timezone=True), server_default=sa.func.now(),
                     nullable=False)  # fmt: skip


def upgrade() -> None:
    # Déjà créé par infra/postgres/init sur une base neuve ; pas forcément ailleurs (tests, Neon).
    op.execute("CREATE SCHEMA IF NOT EXISTS app")
    op.create_table(
        "users",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("email", sa.Text(), nullable=False, unique=True),
        sa.Column("pseudo", sa.Text(), nullable=False, unique=True),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("token_version", sa.Integer(), server_default="0", nullable=False),
        _created_at(),
        sa.CheckConstraint("email = lower(email)", name="users_email_lower"),
        sa.CheckConstraint("pseudo ~ '^[a-z0-9_]{3,20}$'", name="users_pseudo_format"),
        schema="app",
    )
    op.create_table(
        "list_entry",
        sa.Column("user_id", sa.BigInteger(),
                  sa.ForeignKey("app.users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("media_id", sa.BigInteger(),
                  sa.ForeignKey("catalog.media.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("progress", sa.Integer(), server_default="0", nullable=False),
        sa.Column("dropped_at", sa.Integer(), nullable=True),
        sa.Column("score", sa.SmallInteger(), nullable=True),
        sa.Column("review", sa.Text(), nullable=True),
        sa.Column("started_at", sa.Date(), nullable=True),
        sa.Column("finished_at", sa.Date(), nullable=True),
        _created_at(),
        _created_at("updated_at"),
        sa.CheckConstraint("status IN (" + ", ".join(f"'{s}'" for s in STATUSES) + ")",
                           name="list_entry_status"),
        sa.CheckConstraint("progress >= 0", name="list_entry_progress"),
        sa.CheckConstraint(
            "dropped_at IS NULL OR (status = 'dropped' AND dropped_at BETWEEN 0 AND progress)",
            name="list_entry_dropped_at"),
        sa.CheckConstraint("score IS NULL OR score BETWEEN 1 AND 10", name="list_entry_score"),
        sa.CheckConstraint("finished_at IS NULL OR started_at IS NULL OR finished_at >= started_at",
                           name="list_entry_dates"),
        schema="app",
    )  # fmt: skip
    op.create_index("list_entry_user_status_idx", "list_entry", ["user_id", "status"],
                    schema="app")  # fmt: skip
    op.create_index("list_entry_media_idx", "list_entry", ["media_id"], schema="app")
    op.create_table(
        "onboarding_choice",
        sa.Column("user_id", sa.BigInteger(),
                  sa.ForeignKey("app.users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("media_id", sa.BigInteger(),
                  sa.ForeignKey("catalog.media.id", ondelete="CASCADE"), primary_key=True),
        _created_at(),
        schema="app",
    )  # fmt: skip


def downgrade() -> None:
    # Le schéma app lui-même est conservé : il existe avant la 1re migration (script d'init).
    op.drop_table("onboarding_choice", schema="app")
    op.drop_table("list_entry", schema="app")
    op.drop_table("users", schema="app")
