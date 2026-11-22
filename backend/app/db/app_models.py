"""Tables du schéma app (comptes, listes, onboarding) : propriété de l'API.

Contrairement à catalog et mart (créés par le pipeline), ces tables sont créées et modifiées
UNIQUEMENT par les migrations Alembic (backend/migrations). Un test vérifie que ces classes et
les migrations décrivent exactement le même schéma.

Les règles d'intégrité sont aussi posées en base (CHECK, FK) et pas seulement dans Pydantic : un
script, une migration de données ou un futur outil d'admin ne pourront pas écrire une liste
incohérente.
"""

import datetime as dt

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    SmallInteger,
    Text,
    false,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models import Base

SCHEMA = "app"
LIST_STATUSES = ("planning", "in_progress", "completed", "paused", "dropped")
PSEUDO_PATTERN = "^[a-z0-9_]{3,20}$"


def alembic_include_name(name, type_, parent_names) -> bool:
    """Côté base : Alembic ne lit que le schéma app (catalog et mart appartiennent au pipeline)."""
    return type_ != "schema" or name == SCHEMA


def alembic_include_object(obj, name, type_, reflected, compare_to) -> bool:
    """Côté modèles : les classes catalog/mart (lecture seule) ne sont jamais migrées."""
    return type_ != "table" or obj.schema == SCHEMA


class User(Base):
    # « users » et non « user » (SPEC § 5) : user est un mot réservé de Postgres, il faudrait des
    # guillemets dans chaque requête SQL (vues Power BI de la phase 12 comprises).
    __tablename__ = "users"
    __table_args__ = (
        # Email stocké en minuscules : l'unicité ne dépend pas de la casse saisie.
        CheckConstraint("email = lower(email)", name="users_email_lower"),
        CheckConstraint(f"pseudo ~ '{PSEUDO_PATTERN}'", name="users_pseudo_format"),
        {"schema": SCHEMA},
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    email: Mapped[str] = mapped_column(Text, unique=True)
    pseudo: Mapped[str] = mapped_column(Text, unique=True)
    password_hash: Mapped[str] = mapped_column(Text)
    # Incrémenté à la déconnexion (et à la suppression) : tous les jetons déjà émis, qui portent
    # l'ancienne valeur, deviennent invalides. Révocation sans table de sessions (ADR 008).
    token_version: Mapped[int] = mapped_column(Integer, server_default="0")
    # Profil public (/users/{pseudo}) : opt-in, privé par défaut (ADR 011).
    profile_public: Mapped[bool] = mapped_column(Boolean, server_default=false())
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class ListEntry(Base):
    __tablename__ = "list_entry"
    __table_args__ = (
        CheckConstraint(
            "status IN (" + ", ".join(f"'{s}'" for s in LIST_STATUSES) + ")",
            name="list_entry_status",
        ),
        CheckConstraint("progress >= 0", name="list_entry_progress"),
        # « Lâché à l'épisode X » n'a de sens que pour une œuvre abandonnée.
        CheckConstraint(
            "dropped_at IS NULL OR (status = 'dropped' AND dropped_at BETWEEN 0 AND progress)",
            name="list_entry_dropped_at",
        ),
        CheckConstraint("score IS NULL OR score BETWEEN 1 AND 10", name="list_entry_score"),
        CheckConstraint(
            "finished_at IS NULL OR started_at IS NULL OR finished_at >= started_at",
            name="list_entry_dates",
        ),
        # Recherche des entrées d'un statut (onglets de « Ma liste »).
        Index("list_entry_user_status_idx", "user_id", "status"),
        # Suppression d'une œuvre du catalogue (cascade) et statistiques par œuvre (phase 12).
        Index("list_entry_media_idx", "media_id"),
        {"schema": SCHEMA},
    )

    user_id: Mapped[int] = mapped_column(
        ForeignKey("app.users.id", ondelete="CASCADE"), primary_key=True
    )
    # CASCADE aussi côté catalogue : le pipeline retire parfois une œuvre (absente de la source,
    # romans exclus en phase 6). L'entrée disparaît avec elle au lieu de bloquer le pipeline.
    media_id: Mapped[int] = mapped_column(
        ForeignKey("catalog.media.id", ondelete="CASCADE"), primary_key=True
    )
    status: Mapped[str] = mapped_column(Text)
    progress: Mapped[int] = mapped_column(Integer, server_default="0")
    dropped_at: Mapped[int | None] = mapped_column(Integer)
    score: Mapped[int | None] = mapped_column(SmallInteger)
    review: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[dt.date | None] = mapped_column(Date)
    finished_at: Mapped[dt.date | None] = mapped_column(Date)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class OnboardingChoice(Base):
    __tablename__ = "onboarding_choice"
    __table_args__ = {"schema": SCHEMA}

    user_id: Mapped[int] = mapped_column(
        ForeignKey("app.users.id", ondelete="CASCADE"), primary_key=True
    )
    media_id: Mapped[int] = mapped_column(
        ForeignKey("catalog.media.id", ondelete="CASCADE"), primary_key=True
    )
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
