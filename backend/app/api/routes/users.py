"""Profil public : /users/{pseudo} (phase 9, ADR 011). Lisible sans compte."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from app.api.deps import get_rules
from app.core.config import ApiRules
from app.db.session import get_session
from app.schemas.users import PublicProfile
from app.services import profile_service

router = APIRouter(prefix="/users", tags=["profils"])
NO_STORE = {"Cache-Control": "no-store"}


@router.get("/{pseudo}", response_model=PublicProfile)
def public_profile(
    pseudo: str,
    response: Response,
    session: Annotated[Session, Depends(get_session)],
    rules: Annotated[ApiRules, Depends(get_rules)],
) -> dict:
    # Pas de validation par FastAPI (elle répondrait 422) : un pseudo mal formé reçoit la même
    # 404 qu'un profil privé ou inconnu.
    found = profile_service.public_profile(session, pseudo, rules)
    if found is None:
        # no-store aussi sur la 404 : un profil qu'on vient d'ouvrir ne doit pas rester
        # « introuvable » dans un cache (revue de la phase 9).
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Profil introuvable", headers=NO_STORE)
    # Un profil repassé en privé doit disparaître tout de suite : aucun cache, ni navigateur ni CDN.
    response.headers.update(NO_STORE)
    return found
