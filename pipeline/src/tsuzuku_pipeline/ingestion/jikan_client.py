"""Jikan v4 (MyAnimeList, sans clé) : saison en cours, fiche d'un anime, statistiques.

Endpoints (SPEC § 2.2) : GET /seasons/now, GET /anime/{id}, GET /anime/{id}/statistics.
Les réponses sont converties en MediaRecord / StatsRecord ; les contenus adultes sont écartés
avec la même règle que le pipeline (ADR 002 : rating « Rx » ou genre Hentai), en plus du
paramètre sfw=true côté Jikan.
"""

import re
from typing import Any

from tsuzuku_pipeline.ingestion.http import PoliteClient
from tsuzuku_pipeline.ingestion.records import (
    MediaRecord,
    StatsRecord,
    as_float,
    as_int,
    clean_text,
    display_titles,
)


def _names(item: dict[str, Any], *keys: str) -> list[str]:
    return [
        e["name"] for k in keys for e in item.get(k) or [] if isinstance(e, dict) and e.get("name")
    ]


def is_adult(item: dict[str, Any]) -> bool:
    rating = item.get("rating") or ""
    genres = set(_names(item, "genres", "explicit_genres"))
    return rating.startswith("Rx") or "Hentai" in genres


_HOURS = re.compile(r"(\d+)\s*hr")
_MINUTES = re.compile(r"(\d+)\s*min")
_SECONDS = re.compile(r"(\d+)\s*sec")


def duration_minutes(text: str | None) -> float | None:
    """« 24 min per ep », « 1 hr 55 min », « 45 sec » → minutes (comme clean/anime)."""
    if not text:
        return None
    h, m, s = (
        int(x.group(1)) if (x := p.search(text)) else 0 for p in (_HOURS, _MINUTES, _SECONDS)
    )
    total = h * 60 + m + s / 60
    return round(total, 2) if total > 0 else None


def media_record(item: dict[str, Any]) -> MediaRecord:
    """Fiche Jikan (élément de /seasons/now ou data de /anime/{id}) → MediaRecord."""
    images = (item.get("images") or {}).get("jpg") or {}
    year = item.get("year") or (
        ((item.get("aired") or {}).get("prop") or {}).get("from") or {}
    ).get("year")
    title, title_alt = display_titles(item.get("title"), item.get("title_english"))
    cover_url = images.get("large_image_url") or images.get("image_url")
    return MediaRecord(
        kind="anime",
        mal_id=int(item["mal_id"]),
        title=title,
        title_alt=title_alt,
        synopsis=clean_text(item.get("synopsis")),
        episodes=as_int(item.get("episodes")),
        airing_status=item.get("status"),
        format=item.get("type"),
        duration_min=duration_minutes(item.get("duration")),
        start_year=as_int(year),
        creators=tuple(_names(item, "studios")),
        source=item.get("source"),
        age_rating=item.get("rating"),
        cover_url=cover_url,
        cover_source="jikan" if cover_url else None,
        # Rang de popularité MAL (1 = le plus populaire) : même sémantique que le dataset 2020.
        popularity=as_int(item.get("popularity")),
        # Même périmètre que la colonne Genres de MAL dans le dataset : genres, thèmes, démographie.
        genres=tuple(_names(item, "genres", "themes", "demographics")),
    )


def season_now(client: PoliteClient, max_pages: int) -> list[dict[str, Any]]:
    """Animes de la saison en cours (hors adultes), dédoublonnés par mal_id."""
    items: list[dict[str, Any]] = []
    for page in range(1, max_pages + 1):
        body = client.get_json("/seasons/now", params={"sfw": "true", "page": page})
        items.extend(i for i in body.get("data") or [] if isinstance(i, dict) and "mal_id" in i)
        if not (body.get("pagination") or {}).get("has_next_page"):
            break
    unique = {int(i["mal_id"]): i for i in items}
    return [i for i in unique.values() if not is_adult(i)]


def anime(client: PoliteClient, mal_id: int) -> dict[str, Any]:
    return client.get_json(f"/anime/{int(mal_id)}").get("data") or {}


def statistics(client: PoliteClient, item: dict[str, Any]) -> StatsRecord:
    """Statistiques MAL d'un anime ; score et membres viennent de sa fiche."""
    data = client.get_json(f"/anime/{int(item['mal_id'])}/statistics").get("data") or {}
    return StatsRecord(
        mal_id=int(item["mal_id"]),
        score=as_float(item.get("score")),
        members=as_int(item.get("members")),
        watching=as_int(data.get("watching")),
        completed=as_int(data.get("completed")),
        on_hold=as_int(data.get("on_hold")),
        dropped=as_int(data.get("dropped")),
        plan_to_watch=as_int(data.get("plan_to_watch")),
        in_season=bool(item.get("_in_season", True)),
    )


def summary_stats(item: dict[str, Any]) -> StatsRecord:
    """Repli quand /statistics échoue : score et membres (lus dans la fiche) sans le détail par
    statut. L'anime reste ainsi présent dans le snapshot du jour (et dans /trending)."""
    return StatsRecord(
        mal_id=int(item["mal_id"]), score=as_float(item.get("score")),
        members=as_int(item.get("members")), watching=None, completed=None, on_hold=None,
        dropped=None, plan_to_watch=None, in_season=bool(item.get("_in_season", True)),
    )  # fmt: skip
