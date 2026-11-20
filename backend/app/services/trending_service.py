"""Saison en cours : réponse Jikan, reliée à notre catalogue quand l'anime y figure."""

import logging
from typing import Any

from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.clients.jikan import JikanClient
from app.services import catalog_service

logger = logging.getLogger("tsuzuku_api.trending")


def _cover(item: dict[str, Any]) -> str | None:
    images = (item.get("images") or {}).get("jpg") or {}
    return images.get("large_image_url") or images.get("image_url")


def trending(client: JikanClient, session: Session) -> dict[str, Any]:
    items, fetched_at, stale = client.season_now()
    try:
        in_catalog = catalog_service.anime_by_mal(session, [i["mal_id"] for i in items])
    except OperationalError as exc:
        # Base indisponible : la saison reste affichable, seuls les liens au catalogue manquent.
        logger.warning("Catalogue injoignable pour /trending (%s)", type(exc.orig).__name__)
        session.rollback()
        in_catalog = {}
    # Classement : nombre de membres MAL décroissant (l'intérêt du public pour la saison).
    ordered = sorted(items, key=lambda i: -(i.get("members") or 0))
    return {
        "fetched_at": fetched_at,
        "stale": stale,
        "items": [
            {
                "mal_id": i["mal_id"],
                "title": i.get("title") or "",
                "cover_url": _cover(i),
                "score": i.get("score"),
                "members": i.get("members"),
                "episodes": i.get("episodes"),
                "airing_status": i.get("status"),
                "media_id": in_catalog[i["mal_id"]].id if i["mal_id"] in in_catalog else None,
            }
            for i in ordered
        ],
    }
