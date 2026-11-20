"""Liste d'un compte et choix d'onboarding (phase 7).

Toutes les requêtes filtrent sur `user_id` (celui du jeton, jamais celui d'un corps de requête) :
un compte ne peut ni lire ni modifier la liste d'un autre.
"""

from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.config import ApiRules
from app.db.app_models import ListEntry, OnboardingChoice, User
from app.db.models import Media
from app.schemas.demo import LikedItem, ListEntryIn
from app.schemas.me import ListEntryUpdate


class MediaNotFound(Exception):
    pass


class InvalidEntry(ValueError):
    pass


class ListFull(Exception):
    pass


def _lock_account(session: Session, user_id: int) -> None:
    """Verrouille la ligne du compte jusqu'à la fin de la transaction (SELECT … FOR UPDATE).

    Les écritures d'un même compte passent l'une après l'autre : deux PUT simultanés ne
    dépassent pas la taille maximale de liste, et un onboarding envoyé deux fois (double clic)
    ne finit pas en erreur de clé (500). Les autres comptes ne sont pas bloqués.
    """
    session.execute(select(User.id).where(User.id == user_id).with_for_update())


def _total_units(media: Media) -> int | None:
    """Nombre d'épisodes (anime) ou de chapitres (manga…), s'il est connu (> 0)."""
    total = media.episodes if media.kind == "anime" else media.chapters
    return total if total and total > 0 else None


def page(
    session: Session, user_id: int, status: str | None, limit: int, offset: int
) -> dict[str, Any]:
    where = [ListEntry.user_id == user_id]
    if status:
        where.append(ListEntry.status == status)
    total = session.scalar(select(func.count()).select_from(ListEntry).where(*where)) or 0
    rows = session.execute(
        select(ListEntry, Media)
        .join(Media, Media.id == ListEntry.media_id)
        .where(*where)
        # Dernières modifications d'abord, puis id : ordre stable entre deux pages.
        .order_by(ListEntry.updated_at.desc(), ListEntry.media_id)
        .limit(limit)
        .offset(offset)
    ).all()
    return {"total": total, "items": [_out(e, m) for e, m in rows]}


def _out(entry: ListEntry, media: Media) -> dict[str, Any]:
    return {
        "media": media,
        **{c: getattr(entry, c) for c in ("status", "progress", "dropped_at", "score", "review",
                                          "started_at", "finished_at", "updated_at")},
    }  # fmt: skip


def upsert(
    session: Session, user_id: int, media_id: int, body: ListEntryUpdate, rules: ApiRules
) -> dict[str, Any]:
    media = session.get(Media, media_id)
    if media is None:
        raise MediaNotFound(media_id)
    if body.review is not None and len(body.review) > rules.review_max_length:
        raise InvalidEntry(f"critique trop longue (max {rules.review_max_length} caractères)")
    values = body.model_dump()
    total = _total_units(media)
    if body.status == "completed" and total:
        # Terminé = tout vu : la progression saisie (souvent 0 par défaut) ne compte pas.
        values["progress"] = total
    if body.status == "dropped" and body.dropped_at is None:
        values["dropped_at"] = body.progress
    if total:
        for field in ("progress", "dropped_at"):
            if values[field] is not None and values[field] > total:
                raise InvalidEntry(f"{field} ({values[field]}) dépasse le total de l'œuvre "
                                   f"({total})")  # fmt: skip

    _lock_account(session, user_id)
    exists = session.get(ListEntry, (user_id, media_id)) is not None
    if not exists:
        size = session.scalar(
            select(func.count()).select_from(ListEntry).where(ListEntry.user_id == user_id)
        )
        if (size or 0) >= rules.list_max_entries:
            raise ListFull(rules.list_max_entries)
    # INSERT … ON CONFLICT : deux PUT simultanés sur la même œuvre ne lèvent pas d'erreur de clé.
    stmt = insert(ListEntry).values(user_id=user_id, media_id=media_id, **values)
    stmt = stmt.on_conflict_do_update(
        index_elements=[ListEntry.user_id, ListEntry.media_id],
        set_={**values, "updated_at": func.now()},
    ).returning(ListEntry)
    # populate_existing : l'entrée déjà chargée par session.get ci-dessus est rafraîchie avec les
    # valeurs écrites, au lieu de renvoyer l'ancienne version gardée en mémoire par la session.
    entry = session.scalars(stmt, execution_options={"populate_existing": True}).one()
    session.commit()
    return _out(entry, media)


def remove(session: Session, user_id: int, media_id: int) -> bool:
    deleted = session.execute(
        delete(ListEntry).where(ListEntry.user_id == user_id, ListEntry.media_id == media_id)
    ).rowcount
    session.commit()
    return bool(deleted)


def set_onboarding(session: Session, user_id: int, media_ids: list[int], rules: ApiRules) -> int:
    if len(set(media_ids)) != len(media_ids):
        raise InvalidEntry("une même œuvre apparaît plusieurs fois")
    if len(media_ids) < rules.onboarding_min_choices:
        raise InvalidEntry(f"choisis au moins {rules.onboarding_min_choices} œuvres "
                           f"({len(media_ids)} reçues)")  # fmt: skip
    found = set(session.scalars(select(Media.id).where(Media.id.in_(media_ids))))
    missing = sorted(set(media_ids) - found)
    if missing:
        raise InvalidEntry(f"œuvres introuvables : {missing[:10]}")
    # Remplace les choix précédents (refaire l'onboarding), dans une seule transaction.
    _lock_account(session, user_id)
    session.execute(delete(OnboardingChoice).where(OnboardingChoice.user_id == user_id))
    session.add_all(OnboardingChoice(user_id=user_id, media_id=m) for m in media_ids)
    session.commit()
    return len(media_ids)


def reco_inputs(session: Session, user_id: int) -> tuple[list[LikedItem], list[int]]:
    """(titres aimés ou notés, œuvres à exclure des recos) d'après la base.

    - choix d'onboarding : aimés, avec la note par défaut de la fiche du modèle ;
    - entrées notées : leur note (elle l'emporte sur l'onboarding ; une mauvaise note pèse comme
      préférence négative, comme en mode démo) ;
    - toute la liste est exclue : on ne recommande pas ce qui est déjà vu, prévu ou abandonné.
    """
    choices = session.scalars(
        select(OnboardingChoice.media_id).where(OnboardingChoice.user_id == user_id)
    ).all()
    entries = session.execute(
        select(ListEntry.media_id, ListEntry.score).where(ListEntry.user_id == user_id)
    ).all()
    liked = [LikedItem(media_id=m) for m in choices]
    liked += [LikedItem(media_id=m, score=s) for m, s in entries if s is not None]
    return liked, [m for m, _ in entries]


def drop_inputs(session: Session, user_id: int) -> list[ListEntryIn]:
    rows = session.execute(
        select(ListEntry.media_id, ListEntry.status, ListEntry.score)
        .where(ListEntry.user_id == user_id)
    ).all()  # fmt: skip
    return [ListEntryIn(media_id=m, status=st, score=sc) for m, st, sc in rows]
