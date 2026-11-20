"""Enregistrements communs aux sources Jikan et AniList, prêts pour le chargement Postgres.

Python pur (aucun import Spark) : ce module tourne dans l'image Airflow, qui n'a pas PySpark.
"""

import re
from dataclasses import dataclass, field
from html import unescape


@dataclass(frozen=True)
class MediaRecord:
    """Une œuvre, au format des colonnes de catalog.media (+ genres et tags)."""

    kind: str
    title: str
    mal_id: int | None = None
    anilist_id: int | None = None
    title_alt: str | None = None
    synopsis: str | None = None
    episodes: int | None = None
    chapters: int | None = None
    airing_status: str | None = None
    format: str | None = None
    duration_min: float | None = None
    start_year: int | None = None
    creators: tuple[str, ...] = ()
    source: str | None = None
    age_rating: str | None = None
    cover_url: str | None = None
    popularity: int | None = None
    genres: tuple[str, ...] = ()
    tags: tuple[tuple[str, int], ...] = field(default_factory=tuple)  # (nom, rang 0-100)


@dataclass(frozen=True)
class StatsRecord:
    """Statistiques d'un anime à une date (catalog.media_daily_stats)."""

    mal_id: int
    score: float | None
    members: int | None
    watching: int | None
    completed: int | None
    on_hold: int | None
    dropped: int | None
    plan_to_watch: int | None
    in_season: bool = True  # False : anime de la watchlist hors saison en cours


_TAGS = re.compile(r"<[^>]+>")
_SPACES = re.compile(r"[ \t]+")


def clean_text(text: str | None) -> str | None:
    """Synopsis lisible : balises HTML retirées, entités décodées, espaces normalisés."""
    if not text:
        return None
    out = _TAGS.sub(" ", text.replace("<br>", "\n").replace("<br/>", "\n"))
    out = _SPACES.sub(" ", unescape(out))
    out = "\n".join(line.strip() for line in out.splitlines())
    return re.sub(r"\n{3,}", "\n\n", out).strip() or None


def as_int(value: object) -> int | None:
    return int(value) if isinstance(value, int | float) and not isinstance(value, bool) else None


def as_float(value: object) -> float | None:
    return float(value) if isinstance(value, int | float) and not isinstance(value, bool) else None
