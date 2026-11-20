from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_jikan, get_rules
from app.clients.jikan import JikanClient, JikanUnavailable
from app.core.config import ApiRules
from app.db.session import get_session
from app.schemas.trending import TrendingResponse
from app.services import trending_service

router = APIRouter(tags=["tendances"])


@router.get("/trending", response_model=TrendingResponse)
def get_trending(
    session: Annotated[Session, Depends(get_session)],
    client: Annotated[JikanClient, Depends(get_jikan)],
    rules: Annotated[ApiRules, Depends(get_rules)],
) -> TrendingResponse:
    try:
        result = trending_service.trending(client, session, rules.trending_max_age_days)
        return TrendingResponse(**result)
    except JikanUnavailable:
        detail = "Saison en cours indisponible (Jikan ne répond pas)"
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail) from None
