"""Schémas du mode démo : le profil de l'utilisateur est passé dans la requête (pas de compte
avant la phase 7)."""

from typing import Literal

from pydantic import BaseModel, Field, PositiveInt, field_validator

from app.schemas.media import MediaSummary

# Statuts d'une liste Tsuzuku (SPEC § 5, table app.list_entry).
ListStatus = Literal["planning", "in_progress", "completed", "paused", "dropped"]


class LikedItem(BaseModel):
    media_id: PositiveInt
    # Facultative : sans note, un titre aimé vaut la note par défaut d'onboarding (fiche modèle).
    score: int | None = Field(default=None, ge=1, le=10)


class RecoRequest(BaseModel):
    liked: list[LikedItem] = Field(default_factory=list)
    k: int | None = Field(default=None, ge=1)


class RecoItem(BaseModel):
    media: MediaSummary
    score: float
    # « Parce que tu as aimé X » : le titre aimé le plus proche dans l'espace des facteurs.
    because: str | None = None


class RecoResponse(BaseModel):
    # « content » : recos par le contenu (embeddings, phase 10) pour manga, manhwa et manhua.
    strategy: Literal["als", "popularity", "content"]
    reason: str
    liked_used: int
    # Titres ignorés : inconnus, pas des animes, ou absents du modèle (trop peu notés, récents).
    liked_ignored: list[int]
    items: list[RecoItem]


class ListEntryIn(BaseModel):
    media_id: PositiveInt
    status: ListStatus
    score: int | None = Field(default=None, ge=1, le=10)


class DropRiskRequest(BaseModel):
    media_id: PositiveInt
    entries: list[ListEntryIn] = Field(default_factory=list)

    @field_validator("entries")
    @classmethod
    def one_entry_per_media(cls, entries: list[ListEntryIn]) -> list[ListEntryIn]:
        # Une œuvre n'a qu'un statut dans une liste (comme un couple utilisateur-anime côté
        # Spark) : un doublon gonflerait la taille de liste, le taux de drop et les parts de genre.
        ids = [e.media_id for e in entries]
        if len(ids) != len(set(ids)):
            raise ValueError("une même œuvre apparaît plusieurs fois dans la liste")
        return entries


class DropRiskResponse(BaseModel):
    media_id: int
    status: Literal["ok", "insufficient_data"]
    message: str | None = None
    probability: float | None = None
    # Seuil choisi sur la validation (fiche du modèle de drop) : au-dessus, « à risque ».
    threshold: float | None = None
    at_risk: bool | None = None
    entries_used: int = 0
    critical_episode: int | None = None
    point_of_no_return: int | None = None
