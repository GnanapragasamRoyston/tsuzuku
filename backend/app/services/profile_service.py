"""Profil public d'un compte : /users/{pseudo} (phase 9, ADR 011).

Ne renvoie que des agrégats et des notes : jamais l'email, les critiques ni les dates précises
d'activité. Un profil privé et un pseudo inconnu donnent le même résultat (None) : la route
répond la même 404, on ne peut pas savoir qu'un compte existe.
"""

import re
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import ApiRules
from app.db.app_models import LIST_STATUSES, PSEUDO_PATTERN, ListEntry, User
from app.db.models import Genre, Media, MediaGenre

# Œuvres qui comptent pour les goûts : ce qu'on regarde ou a fini, pas ce qu'on prévoit ni lâche.
TASTE_STATUSES = ("in_progress", "completed")


def public_profile(session: Session, pseudo: str, rules: ApiRules) -> dict[str, Any] | None:
    if not re.fullmatch(PSEUDO_PATTERN, pseudo):
        return None
    user = session.scalar(select(User).where(User.pseudo == pseudo, User.profile_public))
    if user is None:
        return None
    mine = ListEntry.user_id == user.id

    by_status = dict(session.execute(
        select(ListEntry.status, func.count()).where(mine).group_by(ListEntry.status)
    ).all())  # fmt: skip
    counts = {s: by_status.get(s, 0) for s in LIST_STATUSES}

    # Épisodes vus : progression des animes seulement (les chapitres ne s'additionnent pas aux
    # épisodes). Terminé = progression remplie au total par list_service.upsert.
    episodes = session.scalar(
        select(func.coalesce(func.sum(ListEntry.progress), 0))
        .join(Media, Media.id == ListEntry.media_id)
        .where(mine, Media.kind == "anime")
    )

    # Taux de drop perso, même définition que le dataset (SPEC § 5) ; caché sous le seuil.
    finished = counts["dropped"] + counts["completed"]
    drop_rate = (
        counts["dropped"] / finished
        if finished >= rules.profile_min_finished_for_drop_rate
        else None
    )

    top_genres = session.scalars(
        select(Genre.name)
        .join(MediaGenre, MediaGenre.genre_id == Genre.id)
        .join(ListEntry, ListEntry.media_id == MediaGenre.media_id)
        .where(mine, ListEntry.status.in_(TASTE_STATUSES))
        .group_by(Genre.name)
        # Ordre stable à égalité : le profil ne change pas d'une visite à l'autre.
        .order_by(func.count().desc(), Genre.name)
        .limit(rules.profile_top_genres)
    ).all()

    scored = session.execute(
        select(ListEntry.score, Media)
        .join(Media, Media.id == ListEntry.media_id)
        .where(mine, ListEntry.score.is_not(None))
        .order_by(ListEntry.updated_at.desc(), ListEntry.media_id)
        .limit(rules.profile_recent_scores)
    ).all()

    return {
        "pseudo": user.pseudo,
        # Mois seulement : assez pour « membre depuis », sans dater l'inscription au jour près.
        "member_since": user.created_at.strftime("%Y-%m"),
        "counts": counts,
        "episodes_watched": int(episodes or 0),
        "drop_rate": drop_rate,
        "top_genres": list(top_genres),
        "recent_scores": [{"media": m, "score": s} for s, m in scored],
    }
