from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_jikan
from app.clients.jikan import JikanClient, JikanUnavailable
from app.db.session import get_session
from app.schemas.trending import TrendingResponse
from app.services import trending_service

router = APIRouter(tags=["tendances"])


@router.get("/trending", response_model=TrendingResponse)
def get_trending(
    session: Annotated[Session, Depends(get_session)],
    client: Annotated[JikanClient, Depends(get_jikan)],
) -> TrendingResponse:
    try:
        return TrendingResponse(**trending_service.trending(client, session))
    except JikanUnavailable:
        detail = "Saison en cours indisponible (Jikan ne répond pas)"
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail) from None
