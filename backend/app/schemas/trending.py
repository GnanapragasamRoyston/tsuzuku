"""Schémas de /trending (saison en cours, source Jikan)."""

from pydantic import BaseModel


class TrendingItem(BaseModel):
    mal_id: int
    title: str
    cover_url: str | None = None
    score: float | None = None
    members: int | None = None
    episodes: int | None = None
    airing_status: str | None = None
    # Lien vers notre catalogue si l'anime y est (dataset 2020) ; None pour une œuvre récente.
    media_id: int | None = None


class TrendingResponse(BaseModel):
    source: str = "Jikan (MyAnimeList)"
    fetched_at: str
    # Vrai si Jikan était indisponible et qu'on sert la dernière réponse connue.
    stale: bool = False
    items: list[TrendingItem]
