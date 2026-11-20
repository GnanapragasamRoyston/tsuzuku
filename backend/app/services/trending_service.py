"""Saison en cours.

Depuis la phase 6, la source principale est la BASE : le DAG jikan_daily_ingest écrit chaque jour
les animes de la saison dans catalog.media_daily_stats. L'API sert ce snapshot (rapide, et aucune
dépendance à une API externe pendant la requête). Si le snapshot manque ou a plus de
`trending_max_age_days` jours (DAG en panne, Jikan indisponible), on se rabat sur un appel direct
à Jikan (cache + retries, app/clients/jikan.py).
"""

import datetime as dt
import logging
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import DBAPIError, OperationalError
from sqlalchemy.orm import Session

from app.clients.jikan import JikanClient
from app.db.models import Media, MediaDailyStats
from app.services import catalog_service

logger = logging.getLogger("tsuzuku_api.trending")

DAILY_SOURCE = "jikan"


def _cover(item: dict[str, Any]) -> str | None:
    images = (item.get("images") or {}).get("jpg") or {}
    return images.get("large_image_url") or images.get("image_url")


def _from_database(session: Session, max_age_days: int, today: dt.date) -> dict[str, Any] | None:
    latest = session.scalar(
        select(func.max(MediaDailyStats.snapshot_date)).where(
            MediaDailyStats.source == DAILY_SOURCE
        )
    )
    if latest is None or (today - latest).days > max_age_days:
        return None
    rows = session.execute(
        select(Media, MediaDailyStats)
        .join(MediaDailyStats, MediaDailyStats.media_id == Media.id)
        .where(
            MediaDailyStats.snapshot_date == latest,
            MediaDailyStats.source == DAILY_SOURCE,
            # Même périmètre que le repli en direct (/seasons/now) : la saison, pas la watchlist.
            MediaDailyStats.in_season.is_(True),
        )  # fmt: skip
        # Classement : nombre de membres MAL décroissant (l'intérêt du public pour la saison).
        .order_by(MediaDailyStats.members.desc().nulls_last(), Media.id)
    ).all()
    return {
        "origin": "database",
        "fetched_at": latest.isoformat(),
        "stale": False,
        "items": [
            {
                "mal_id": m.mal_id,
                "title": m.title,
                "cover_url": m.cover_url,
                "score": s.score,
                "members": s.members,
                "episodes": m.episodes,
                "airing_status": m.airing_status,
                "media_id": m.id,
            }  # fmt: skip
            for m, s in rows
        ],
    }


def _from_jikan(client: JikanClient, session: Session) -> dict[str, Any]:
    items, fetched_at, stale = client.season_now()
    try:
        in_catalog = catalog_service.anime_by_mal(session, [i["mal_id"] for i in items])
    except OperationalError as exc:
        # Base indisponible : la saison reste affichable, seuls les liens au catalogue manquent.
        logger.warning("Catalogue injoignable pour /trending (%s)", type(exc.orig).__name__)
        session.rollback()
        in_catalog = {}
    ordered = sorted(items, key=lambda i: -(i.get("members") or 0))
    return {
        "origin": "live",
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


def trending(
    client: JikanClient, session: Session, max_age_days: int, today: dt.date | None = None
) -> dict[str, Any]:
    today = today or dt.datetime.now(dt.UTC).date()
    try:
        snapshot = _from_database(session, max_age_days, today)
    except DBAPIError as exc:
        # Base injoignable (OperationalError) OU table pas encore créée (ProgrammingError :
        # ni make spark ni DAG n'ont tourné) : la saison reste servie par Jikan en direct.
        logger.warning("Snapshot de la saison illisible (%s) : appel direct à Jikan",
                       type(exc.orig).__name__)  # fmt: skip
        session.rollback()
        snapshot = None
    if snapshot is not None and snapshot["items"]:
        return snapshot
    logger.info("Pas de snapshot récent de la saison : appel direct à Jikan")
    return _from_jikan(client, session)
