"""Lecture du catalogue et des marts.

Les modèles (ALS, drop) parlent en identifiants MAL ; l'API et le front parlent en
catalog.media.id. Les conversions se font ici, et seulement ici.
"""

from collections.abc import Iterable

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session
from tsuzuku_ml.drop_features import AnimeInfo

from app.db.models import CriticalEpisode, DropCurve, Genre, Media, MediaGenre

# Seules les œuvres du dataset d'entraînement ont des features comparables à l'entraînement :
# une œuvre ajoutée plus tard (Jikan, AniList) n'existait pas pour le modèle de drop.
TRAINING_SOURCE = "mal_kaggle_2020"


def _like_pattern(q: str) -> str:
    # % et _ sont des jokers en SQL : on les échappe pour chercher le texte tel quel.
    escaped = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _rank():
    """Rang de popularité, 1 = le plus populaire. 0 veut dire « non classé » chez MAL (œuvre pas
    encore sortie en 2020) : traité comme inconnu, sinon ces titres passeraient en tête."""
    return func.nullif(Media.popularity, 0)


def search(session: Session, q: str, kinds: list[str], limit: int) -> list[Media]:
    pattern = _like_pattern(q)
    stmt = select(Media).where(
        or_(Media.title.ilike(pattern, escape="\\"), Media.title_alt.ilike(pattern, escape="\\"))
    )
    if kinds:
        stmt = stmt.where(Media.kind.in_(kinds))
    # Tri par rang croissant, inconnus à la fin.
    stmt = stmt.order_by(_rank().asc().nulls_last(), Media.id).limit(limit)
    return list(session.scalars(stmt))


def popular(session: Session, kinds: list[str], limit: int, offset: int) -> list[Media]:
    """Œuvres classées les plus populaires des types demandés (accueil, onboarding).

    Les rangs des animes (MAL) et des mangas/manhwas/manhuas (AniList) viennent de deux sources :
    on ne mélange un anime et un manga dans une même liste que si on les demande ensemble.
    """
    stmt = (
        select(Media)
        .where(Media.kind.in_(kinds), _rank().is_not(None))
        .order_by(_rank().asc(), Media.id)
        .limit(limit)
        .offset(offset)
    )
    return list(session.scalars(stmt))


def genres_by_media(session: Session, media_ids: Iterable[int]) -> dict[int, list[str]]:
    ids = list(media_ids)
    if not ids:
        return {}
    rows = session.execute(
        select(MediaGenre.media_id, Genre.name)
        .join(Genre, Genre.id == MediaGenre.genre_id)
        .where(MediaGenre.media_id.in_(ids))
        .order_by(MediaGenre.media_id, Genre.name)
    )
    out: dict[int, list[str]] = {i: [] for i in ids}
    for media_id, name in rows:
        out[media_id].append(name)
    return out


def detail(session: Session, media_id: int) -> dict | None:
    media = session.get(Media, media_id)
    if media is None:
        return None
    curve = session.scalars(
        select(DropCurve).where(DropCurve.media_id == media_id).order_by(DropCurve.episode)
    ).all()
    return {
        "media": media,
        "genres": genres_by_media(session, [media_id])[media_id],
        "critical": session.get(CriticalEpisode, media_id),
        "drop_curve": list(curve),
    }


def media_by_ids(session: Session, ids: Iterable[int]) -> dict[int, Media]:
    ids = list(set(ids))
    if not ids:
        return {}
    return {m.id: m for m in session.scalars(select(Media).where(Media.id.in_(ids)))}


def anime_by_mal(session: Session, mal_ids: Iterable[int]) -> dict[int, Media]:
    ids = [int(i) for i in set(mal_ids)]
    if not ids:
        return {}
    stmt = select(Media).where(Media.kind == "anime", Media.mal_id.in_(ids))
    return {m.mal_id: m for m in session.scalars(stmt)}


def anime_infos(session: Session, media: Iterable[Media]) -> dict[int, AnimeInfo]:
    """Infos d'anime au format des features de drop, indexées par mal_id.

    Même correspondance de colonnes que l'entraînement (catalog.media est construit depuis
    clean/anime : format = type, creators = studios, age_rating = rating).
    """
    rows = [m for m in media if m.kind == "anime" and m.mal_id and m.data_source == TRAINING_SOURCE]
    genres = genres_by_media(session, [m.id for m in rows])
    return {
        m.mal_id: AnimeInfo(
            genres=tuple(genres[m.id]),
            format=m.format,
            episodes=m.episodes,
            duration_min=m.duration_min,
            source=m.source,
            start_year=m.start_year,
            age_rating=m.age_rating,
            popularity=m.popularity,
            studios=tuple(m.creators or ()),
        )
        for m in rows
    }
