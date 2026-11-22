"""« Proposer une jaquette » : validation de l'URL et file de modération (ADR 012).

L'URL n'est JAMAIS téléchargée par l'API (pas de requête vers une adresse choisie par un
utilisateur : pas de SSRF). Elle est seulement vérifiée, stockée, puis validée par Royston ; le
front ne l'affiche qu'après, via l'optimiseur d'images de Next limité aux mêmes domaines.
"""

import datetime as dt
from urllib.parse import urlsplit

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.config import ApiRules
from app.db.app_models import CoverSuggestion
from app.db.models import Media
from app.services import list_service


class InvalidCoverUrl(ValueError):
    pass


class MediaNotFound(Exception):
    pass


class AlreadySuggested(Exception):
    pass


class TooManySuggestions(Exception):
    pass


def check_url(url: str, rules: ApiRules) -> str:
    """URL acceptée telle quelle, ou InvalidCoverUrl. Stricte : HTTPS, hôte et chemin dans la
    liste, ni identifiants, ni port, ni paramètres, ni remontée de dossier."""
    if len(url) > rules.cover_url_max_length:
        raise InvalidCoverUrl("adresse trop longue")
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError:
        raise InvalidCoverUrl("adresse invalide") from None
    if parts.scheme != "https" or parts.username or parts.password or port is not None:
        raise InvalidCoverUrl("adresse HTTPS simple attendue")
    # « % » refusé : un « %2e%2e » encodé passerait la vérification des « .. » puis serait décodé
    # par le CDN (revue du lot qualité). Les vraies adresses d'images n'en contiennent pas.
    if parts.query or parts.fragment or "\\" in url or "%" in url or ".." in parts.path.split("/"):
        raise InvalidCoverUrl("adresse d'image sans paramètres attendue")
    # Reconstruite à partir de ses morceaux : une adresse « bizarre » (majuscules dans l'hôte,
    # encodages) ne correspond pas et est refusée plutôt qu'interprétée.
    if f"https://{parts.hostname}{parts.path}" != url or not any(
        url.startswith(prefix) for prefix in rules.cover_suggestion_prefixes
    ):
        raise InvalidCoverUrl("images d'AniList, MyAnimeList ou Kitsu seulement")
    return url


def suggest(session: Session, user_id: int, media_id: int, url: str, rules: ApiRules) -> None:
    url = check_url(url, rules)
    if session.get(Media, media_id) is None:
        raise MediaNotFound(media_id)
    # Verrou du compte (même mécanisme que la liste) : des envois simultanés ne peuvent pas
    # dépasser la limite quotidienne en passant tous le comptage en même temps.
    list_service.lock_account(session, user_id)
    already = session.scalar(
        select(CoverSuggestion.id).where(
            CoverSuggestion.user_id == user_id,
            CoverSuggestion.media_id == media_id,
            CoverSuggestion.url == url,
        )
    )
    if already is not None:
        # Avant la limite : renvoyer une image déjà proposée dit « déjà proposée », pas « trop ».
        session.rollback()
        raise AlreadySuggested(url)
    since = dt.datetime.now(dt.UTC) - dt.timedelta(days=1)
    today = session.scalar(
        select(func.count()).select_from(CoverSuggestion)
        .where(CoverSuggestion.user_id == user_id, CoverSuggestion.created_at >= since)
    )  # fmt: skip
    if (today or 0) >= rules.cover_suggestions_per_day:
        session.rollback()
        raise TooManySuggestions(rules.cover_suggestions_per_day)
    # ON CONFLICT DO NOTHING : deux envois simultanés de la même image ne lèvent pas d'erreur de
    # clé ; « rien d'inséré » veut dire « déjà proposée ».
    inserted = session.execute(
        insert(CoverSuggestion)
        .values(user_id=user_id, media_id=media_id, url=url)
        .on_conflict_do_nothing(constraint="cover_suggestion_once")
        .returning(CoverSuggestion.id)
    ).first()
    session.commit()
    if inserted is None:
        raise AlreadySuggested(url)
