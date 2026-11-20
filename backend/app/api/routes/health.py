import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.db.session import get_session

router = APIRouter(tags=["santé"])
logger = logging.getLogger("tsuzuku_api")


def _state(request: Request, session: Session) -> dict:
    try:
        session.execute(text("SELECT 1"))
        database = "ok"
    except SQLAlchemyError as exc:
        # Nom de l'erreur seulement : son message peut contenir l'URL de connexion.
        logger.warning("Base injoignable (%s)", type(exc).__name__)
        database = "unavailable"
    state = request.app.state
    models = {
        "reco": "ok" if state.reco is not None else "unavailable",
        "drop": "ok" if state.drop is not None else "unavailable",
    }
    ok = database == "ok" and all(v == "ok" for v in models.values())
    return {"status": "ok" if ok else "degraded", "database": database, "models": models}


@router.get("/health")
def health(request: Request, session: Annotated[Session, Depends(get_session)]) -> dict:
    """Vivacité : répond toujours 200 tant que le processus tourne ; `status` vaut « degraded »
    si une dépendance manque (healthcheck Docker : on ne redémarre pas l'API pour autant)."""
    return _state(request, session)


@router.get("/health/ready")
def ready(request: Request, session: Annotated[Session, Depends(get_session)]) -> JSONResponse:
    """Disponibilité : 503 si la base ou un modèle manque (prêt à recevoir du trafic ?)."""
    body = _state(request, session)
    return JSONResponse(body, status_code=200 if body["status"] == "ok" else 503)
