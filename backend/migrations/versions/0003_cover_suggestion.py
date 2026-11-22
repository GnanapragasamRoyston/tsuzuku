"""Propositions de jaquettes (lot « qualité des jaquettes », ADR 012).

Un utilisateur colle l'URL d'une image d'un domaine autorisé ; Royston valide ou refuse en
ligne de commande (scripts/covers_review.py). L'API ne télécharge jamais l'URL proposée.

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "cover_suggestion",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("user_id", sa.BigInteger(),
                  sa.ForeignKey("app.users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("media_id", sa.BigInteger(),
                  sa.ForeignKey("catalog.media.id", ondelete="CASCADE"), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), server_default="pending", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
                  nullable=False),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("status IN ('pending', 'approved', 'rejected')",
                           name="cover_suggestion_status"),
        sa.UniqueConstraint("user_id", "media_id", "url", name="cover_suggestion_once"),
        schema="app",
    )  # fmt: skip
    op.create_index("cover_suggestion_status_idx", "cover_suggestion", ["status", "created_at"],
                    schema="app")  # fmt: skip
    op.create_index("cover_suggestion_user_idx", "cover_suggestion", ["user_id", "created_at"],
                    schema="app")  # fmt: skip


def downgrade() -> None:
    op.drop_table("cover_suggestion", schema="app")
