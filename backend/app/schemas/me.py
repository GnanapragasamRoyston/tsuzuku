"""Schémas des routes /me (liste, onboarding, export RGPD), phase 7."""

import datetime as dt

from pydantic import BaseModel, ConfigDict, Field, PositiveInt, model_validator

from app.schemas.demo import ListStatus
from app.schemas.media import MediaSummary


class ListEntryUpdate(BaseModel):
    """Corps de PUT /me/list/{media_id} : l'entrée ENTIÈRE (un champ absent est remis à vide).

    Les règles qui dépendent de l'œuvre (progression ≤ nombre d'épisodes) ou de settings.yaml
    (longueur de la critique) sont vérifiées par le service.
    """

    model_config = ConfigDict(extra="forbid")

    status: ListStatus
    progress: int = Field(default=0, ge=0, le=100_000)
    # « Lâché à l'épisode / au chapitre X ». Absent avec le statut dropped → la progression.
    dropped_at: int | None = Field(default=None, ge=0, le=100_000)
    score: int | None = Field(default=None, ge=1, le=10)
    # Borne large de sécurité (un corps énorme est refusé tôt) ; la vraie limite, plus basse,
    # vient de settings.yaml (review_max_length) et est vérifiée par le service.
    review: str | None = Field(default=None, max_length=10_000)
    started_at: dt.date | None = None
    finished_at: dt.date | None = None

    @model_validator(mode="after")
    def coherent(self) -> "ListEntryUpdate":
        if self.dropped_at is not None and self.status != "dropped":
            raise ValueError("dropped_at n'est permis qu'avec le statut « dropped »")
        if self.dropped_at is not None and self.dropped_at > self.progress:
            # On ne lâche pas après le dernier épisode vu (vrai même si le total est inconnu).
            raise ValueError("dropped_at ne peut pas dépasser la progression")
        if self.started_at and self.finished_at and self.finished_at < self.started_at:
            raise ValueError("finished_at est antérieur à started_at")
        return self


class ListEntryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    media: MediaSummary
    status: ListStatus
    progress: int
    dropped_at: int | None
    score: int | None
    review: str | None
    started_at: dt.date | None
    finished_at: dt.date | None
    updated_at: dt.datetime


class ListPage(BaseModel):
    total: int
    # Nombre d'œuvres par statut sur toute la liste (indépendant du filtre de la page).
    counts: dict[ListStatus, int]
    items: list[ListEntryOut]


class OnboardingRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Borne large ici ; le minimum (settings.yaml) est vérifié par le service.
    media_ids: list[PositiveInt] = Field(max_length=500)


class OnboardingResponse(BaseModel):
    count: int


class ExportListEntry(BaseModel):
    media_id: int
    title: str
    kind: str
    status: str
    progress: int
    dropped_at: int | None
    score: int | None
    review: str | None
    started_at: dt.date | None
    finished_at: dt.date | None
    created_at: dt.datetime
    updated_at: dt.datetime


class ExportOnboardingChoice(BaseModel):
    media_id: int
    title: str
    created_at: dt.datetime


class ExportUser(BaseModel):
    id: int
    email: str
    pseudo: str
    created_at: dt.datetime
    profile_public: bool


class AccountExport(BaseModel):
    """Toutes les données personnelles du compte (droit d'accès et de portabilité, RGPD art. 15
    et 20). Le hash du mot de passe et la version de jeton n'en font pas partie : ce sont des
    données de sécurité, pas des données fournies par la personne."""

    exported_at: dt.datetime
    user: ExportUser
    list: list[ExportListEntry]
    onboarding: list[ExportOnboardingChoice]
