"""Comptes : création, authentification, révocation des sessions, suppression, export RGPD.

Journalisation : uniquement l'id du compte, jamais l'email ni le mot de passe (CLAUDE.md § 10).
"""

import datetime as dt
import logging

from sqlalchemy import exists, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import AuthRules
from app.core.security import PasswordHasher
from app.db.app_models import CoverSuggestion, ListEntry, OnboardingChoice, User
from app.db.models import Media
from app.schemas.auth import RegisterRequest

logger = logging.getLogger("tsuzuku_api")


class AccountExists(Exception):
    """Email ou pseudo déjà pris."""


class WeakPassword(ValueError):
    pass


def check_password(password: str, rules: AuthRules) -> None:
    if not rules.password_min_length <= len(password) <= rules.password_max_length:
        raise WeakPassword(
            f"le mot de passe doit faire entre {rules.password_min_length} et "
            f"{rules.password_max_length} caractères"
        )


def register(
    session: Session, hasher: PasswordHasher, rules: AuthRules, body: RegisterRequest
) -> User:
    check_password(body.password, rules)
    user = User(email=body.email, pseudo=body.pseudo, password_hash=hasher.hash(body.password))
    session.add(user)
    try:
        session.commit()
    except IntegrityError:
        # Contrainte UNIQUE en base (et non un SELECT avant l'INSERT) : deux inscriptions
        # simultanées avec le même email ne peuvent pas passer toutes les deux.
        session.rollback()
        raise AccountExists from None
    logger.info("Compte créé (id %s)", user.id)
    return user


def authenticate(
    session: Session, hasher: PasswordHasher, email: str, password: str
) -> User | None:
    user = session.scalar(select(User).where(User.email == email))
    # Toujours une vérification argon2, compte trouvé ou non (même durée de réponse).
    if not hasher.verify(user.password_hash if user else None, password) or user is None:
        return None
    if hasher.needs_rehash(user.password_hash):
        user.password_hash = hasher.hash(password)
        session.commit()
    return user


def revoke_sessions(session: Session, user_id: int) -> None:
    # Incrément atomique en SQL : deux déconnexions simultanées ne se marchent pas dessus.
    session.execute(
        update(User).where(User.id == user_id).values(token_version=User.token_version + 1)
    )
    session.commit()


def delete_account(session: Session, user: User) -> None:
    # Liste et choix d'onboarding suivent par ON DELETE CASCADE (contrainte en base).
    session.delete(user)
    session.commit()
    logger.info("Compte supprimé (id %s)", user.id)


def profile(session: Session, user: User) -> dict:
    onboarded = session.scalar(select(exists().where(OnboardingChoice.user_id == user.id)))
    size = session.scalar(select(func.count()).where(ListEntry.user_id == user.id))
    return {
        "id": user.id,
        "email": user.email,
        "pseudo": user.pseudo,
        "created_at": user.created_at,
        "onboarding_done": bool(onboarded),
        "list_size": size or 0,
        "profile_public": user.profile_public,
    }


def export(session: Session, user: User) -> dict:
    entries = session.execute(
        select(ListEntry, Media.title, Media.kind)
        .join(Media, Media.id == ListEntry.media_id)
        .where(ListEntry.user_id == user.id)
        .order_by(ListEntry.updated_at.desc())
    ).all()
    choices = session.execute(
        select(OnboardingChoice, Media.title)
        .join(Media, Media.id == OnboardingChoice.media_id)
        .where(OnboardingChoice.user_id == user.id)
        .order_by(OnboardingChoice.media_id)
    ).all()
    suggestions = session.execute(
        select(CoverSuggestion, Media.title)
        .join(Media, Media.id == CoverSuggestion.media_id)
        .where(CoverSuggestion.user_id == user.id)
        .order_by(CoverSuggestion.created_at)
    ).all()
    return {
        "exported_at": dt.datetime.now(dt.UTC),
        "user": {
            "id": user.id,
            "email": user.email,
            "pseudo": user.pseudo,
            "created_at": user.created_at,
            "profile_public": user.profile_public,
        },  # fmt: skip
        "list": [
            {
                "media_id": e.media_id,
                "title": title,
                "kind": kind,
                "status": e.status,
                "progress": e.progress,
                "dropped_at": e.dropped_at,
                "score": e.score,
                "review": e.review,
                "started_at": e.started_at,
                "finished_at": e.finished_at,
                "created_at": e.created_at,
                "updated_at": e.updated_at,
            }
            for e, title, kind in entries
        ],  # fmt: skip
        "onboarding": [
            {"media_id": c.media_id, "title": title, "created_at": c.created_at}
            for c, title in choices
        ],
        "cover_suggestions": [
            {
                "media_id": c.media_id,
                "title": title,
                "url": c.url,
                "status": c.status,
                "created_at": c.created_at,
            }
            for c, title in suggestions
        ],  # fmt: skip
    }
