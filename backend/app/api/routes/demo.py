"""Mode démo (phase 5) : le profil de l'utilisateur est passé dans la requête.

Les routes /me/... (phase 7) appelleront les mêmes services avec la liste lue en base.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_drop_engine, get_reco_engine, get_rules
from app.core.config import ApiRules
from app.db.session import get_session
from app.schemas.demo import DropRiskRequest, DropRiskResponse, RecoRequest, RecoResponse
from app.services import drop_service, reco_service

router = APIRouter(prefix="/demo", tags=["démo"])


def _check_list_size(n: int, rules: ApiRules) -> None:
    if n > rules.max_list_items:
        detail = f"liste trop longue : {n} éléments (max {rules.max_list_items})"
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail)


@router.post("/recommendations", response_model=RecoResponse)
def demo_recommendations(
    body: RecoRequest,
    session: Annotated[Session, Depends(get_session)],
    rules: Annotated[ApiRules, Depends(get_rules)],
    engine: Annotated[reco_service.RecoEngine, Depends(get_reco_engine)],
) -> RecoResponse:
    _check_list_size(len(body.liked), rules)
    k = min(body.k or rules.default_k, rules.max_k)
    return RecoResponse.model_validate(
        reco_service.recommend_for(engine, session, body.liked, k), from_attributes=True
    )


@router.post("/drop-risk", response_model=DropRiskResponse)
def demo_drop_risk(
    body: DropRiskRequest,
    session: Annotated[Session, Depends(get_session)],
    rules: Annotated[ApiRules, Depends(get_rules)],
    engine: Annotated[drop_service.DropEngine, Depends(get_drop_engine)],
) -> DropRiskResponse:
    _check_list_size(len(body.entries), rules)
    try:
        result = drop_service.drop_risk(engine, session, body.media_id, body.entries)
    except drop_service.MediaNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND,
                            f"Œuvre {body.media_id} introuvable") from None  # fmt: skip
    return DropRiskResponse(**result)
