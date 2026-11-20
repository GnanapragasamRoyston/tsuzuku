"""Dépendances FastAPI : accès à l'état chargé au démarrage (règles, modèles, client Jikan)."""

from fastapi import HTTPException, Request, status

from app.clients.jikan import JikanClient
from app.core.config import ApiRules
from app.services.drop_service import DropEngine
from app.services.reco_service import RecoEngine


def get_rules(request: Request) -> ApiRules:
    return request.app.state.rules


def get_reco_engine(request: Request) -> RecoEngine:
    engine = request.app.state.reco
    if engine is None:
        # 503 et non 500 : l'API fonctionne, c'est le modèle qui manque (make reco à lancer).
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE,
                            "Modèle de recommandation indisponible")  # fmt: skip
    return engine


def get_drop_engine(request: Request) -> DropEngine:
    engine = request.app.state.drop
    if engine is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE,
                            "Modèle de risque de drop indisponible")  # fmt: skip
    return engine


def get_jikan(request: Request) -> JikanClient:
    return request.app.state.jikan
