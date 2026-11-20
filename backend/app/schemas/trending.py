"""Schémas de /trending (saison en cours, source Jikan)."""

from typing import Literal

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
    # « database » : snapshot du DAG jikan_daily_ingest ; « live » : appel direct à Jikan (repli).
    origin: Literal["database", "live"]
    # Date du snapshot (base) ou heure de récupération (appel direct).
    fetched_at: str
    # Vrai si Jikan était indisponible et qu'on sert la dernière réponse connue.
    stale: bool = False
    items: list[TrendingItem]
