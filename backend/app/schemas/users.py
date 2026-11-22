"""Schémas du profil public (phase 9)."""

from pydantic import BaseModel

from app.schemas.media import MediaSummary


class ScoredMedia(BaseModel):
    media: MediaSummary
    score: int


class PublicProfile(BaseModel):
    pseudo: str
    member_since: str  # « 2026-11 » : mois d'inscription seulement
    counts: dict[str, int]
    episodes_watched: int
    # None sous le seuil de settings.yaml (profile_min_finished_for_drop_rate).
    drop_rate: float | None
    top_genres: list[str]
    recent_scores: list[ScoredMedia]
