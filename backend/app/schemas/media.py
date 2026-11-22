"""Schémas des routes /media."""

import datetime as dt

from pydantic import BaseModel, ConfigDict


class MediaSummary(BaseModel):
    """Ce qu'il faut pour afficher une carte d'œuvre."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    kind: str
    title: str
    title_alt: str | None = None
    format: str | None = None
    episodes: int | None = None
    chapters: int | None = None
    start_year: int | None = None
    cover_url: str | None = None
    popularity: int | None = None


class DropCurvePoint(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    episode: int
    nb_drops: int
    cumulative_share: float


class CriticalEpisodeOut(BaseModel):
    """Indicateurs de drop de l'œuvre (définitions : README § Définitions, ADR 003)."""

    model_config = ConfigDict(from_attributes=True)

    critical_episode: int
    critical_drop_share: float
    initial_drop_risk: float | None = None
    point_of_no_return: int | None = None
    drop_rate: float
    nb_drops: int
    nb_completed: int


class DailyStatsOut(BaseModel):
    """Dernier snapshot Jikan de l'œuvre (DAG jikan_daily_ingest, phase 6)."""

    model_config = ConfigDict(from_attributes=True)

    snapshot_date: dt.date
    score: float | None
    members: int | None


class MediaDetail(MediaSummary):
    synopsis: str | None = None
    airing_status: str | None = None
    duration_min: float | None = None
    creators: list[str] = []
    source: str | None = None
    age_rating: str | None = None
    genres: list[str] = []
    # Absents si l'œuvre n'a pas assez de drops pour un indicateur fiable (seuils du pipeline).
    critical: CriticalEpisodeOut | None = None
    drop_curve: list[DropCurvePoint] = []
    # None tant que Jikan n'a rien fourni pour cette œuvre (panne connue depuis la phase 6).
    latest_stats: DailyStatsOut | None = None


class SearchResponse(BaseModel):
    query: str
    items: list[MediaSummary]


class PopularResponse(BaseModel):
    items: list[MediaSummary]
