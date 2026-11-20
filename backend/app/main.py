"""Point d'entrée de l'API Tsuzuku (phase 5 : catalogue, tendances, démo reco et risque de drop).

Lancement : `uvicorn app.main:create_app --factory` (make api, ou le conteneur Docker).
Fabrique plutôt qu'objet global : les tests créent une app avec leurs propres réglages, sans
dépendre de variables d'environnement lues à l'import.
"""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.exc import OperationalError
from tsuzuku_ml.artifacts import check_reco_parity, load_drop_model, load_reco_model

from app.api.routes import demo, health, media, trending
from app.clients.jikan import JikanClient
from app.core.config import ApiRules, Settings, get_settings, load_rules
from app.db.session import make_engine, make_sessionmaker
from app.services.drop_service import DropEngine
from app.services.reco_service import RecoEngine

logger = logging.getLogger("tsuzuku_api")


def _load_models(
    settings: Settings, rules: ApiRules
) -> tuple[RecoEngine | None, DropEngine | None]:
    """Charge et vérifie les modèles. Un modèle absent ou invalide n'empêche pas l'API de
    démarrer : ses routes répondent 503 et /health le signale."""
    reco = drop = None
    # Exception large, volontairement : un pickle corrompu peut lever presque n'importe quoi
    # (UnpicklingError, AttributeError, EOFError…). Planter ici ferait boucler le conteneur au
    # redémarrage ; on préfère une API qui démarre en « degraded ».
    try:
        model, card = load_reco_model(settings.models_dir)
        check_reco_parity(model, card)  # même entrée → même top 10 qu'à l'entraînement
        reco = RecoEngine(model, card, rules.min_liked_for_als)
        logger.info("Modèle de reco chargé (run %s)", card.get("run_id"))
    except Exception as exc:  # noqa: BLE001
        logger.error("Modèle de reco indisponible (%s) : %s", type(exc).__name__, exc)
    try:
        model, card = load_drop_model(settings.models_dir)
        drop = DropEngine(model, card)
        logger.info("Modèle de drop chargé (run %s)", card.get("run_id"))
    except Exception as exc:  # noqa: BLE001
        logger.error("Modèle de drop indisponible (%s) : %s", type(exc).__name__, exc)
    return reco, drop


async def _database_unavailable(request: Request, exc: OperationalError) -> JSONResponse:
    # Base coupée ou injoignable : 503 (réessayer plus tard), pas 500. Seul le NOM de l'erreur
    # est journalisé : son message peut contenir l'URL de connexion.
    logger.error("Base de données indisponible (%s)", type(exc.orig).__name__)
    return JSONResponse({"detail": "Base de données indisponible"}, status_code=503)


def create_app(
    settings: Settings | None = None,
    rules: ApiRules | None = None,
    jikan_transport: httpx.BaseTransport | None = None,
) -> FastAPI:
    settings = settings or get_settings()
    rules = rules or load_rules(settings.settings_file)
    # uvicorn ne configure que ses propres loggers : sans ça, « Modèle chargé » ou « Jikan
    # indisponible » n'apparaîtraient pas dans `docker logs`. Sans effet si déjà configuré.
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s | %(message)s"
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        engine = make_engine(settings.database_url)
        app.state.rules = rules
        app.state.sessionmaker = make_sessionmaker(engine)
        app.state.reco, app.state.drop = _load_models(settings, rules)
        app.state.jikan = JikanClient(rules.jikan, transport=jikan_transport)
        yield
        app.state.jikan.close()
        engine.dispose()

    app = FastAPI(
        title="Tsuzuku API",
        version="0.5.0",
        description="Catalogue, saison en cours, recommandations et risque de drop (mode démo).",
        lifespan=lifespan,
    )
    # CORS restreint au front (SPEC § 7) : jamais « * ».
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
    )
    app.add_exception_handler(OperationalError, _database_unavailable)
    for router in (health.router, media.router, trending.router, demo.router):
        app.include_router(router)
    return app
