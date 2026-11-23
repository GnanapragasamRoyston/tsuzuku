"""Point d'entrée de l'API Tsuzuku : catalogue, tendances, démo (phase 5), comptes et listes
(phase 7).

Lancement : `uvicorn app.main:create_app --factory` (make api, ou le conteneur Docker).
Fabrique plutôt qu'objet global : les tests créent une app avec leurs propres réglages, sans
dépendre de variables d'environnement lues à l'import.
"""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.exc import OperationalError
from tsuzuku_ml.artifacts import check_reco_parity, load_drop_model, load_reco_model

from app.api.deps import AuthState
from app.api.routes import auth, demo, health, me, media, trending, users
from app.clients.jikan import JikanClient
from app.core.config import ApiRules, Settings, get_settings, load_rules
from app.core.model_store import download_models
from app.core.trusted_proxy import TrustedProxyMiddleware
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
    if settings.models_uri:
        try:
            download_models(settings.models_uri, settings.models_dir)
            logger.info("Modèles copiés depuis %s", settings.models_uri)
        except Exception as exc:  # noqa: BLE001
            # Même règle que ci-dessous : l'API démarre en « degraded » plutôt que de boucler.
            logger.error("Copie des modèles impossible (%s) : %s", type(exc).__name__, exc)
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


MIN_SECRET_LENGTH = 32


def _auth_state(settings: Settings, rules: ApiRules) -> AuthState | None:
    """Comptes activés seulement avec un secret assez long. Sinon l'API démarre quand même
    (catalogue, démo) et les routes de compte répondent 503."""
    secret = settings.jwt_secret.get_secret_value() if settings.jwt_secret else ""
    if len(secret) < MIN_SECRET_LENGTH:
        logger.error("Comptes désactivés : JWT_SECRET absent ou trop court (make api-keys)")
        return None
    if not settings.cookie_secure:
        logger.warning("COOKIE_SECURE=false : cookie de session envoyé en http (local uniquement)")
    return AuthState.build(secret, rules.auth, settings.cookie_secure)


async def _database_unavailable(request: Request, exc: OperationalError) -> JSONResponse:
    # Base coupée ou injoignable : 503 (réessayer plus tard), pas 500. Seul le NOM de l'erreur
    # est journalisé : son message peut contenir l'URL de connexion.
    logger.error("Base de données indisponible (%s)", type(exc.orig).__name__)
    return JSONResponse({"detail": "Base de données indisponible"}, status_code=503)


async def _invalid_request(request: Request, exc: RequestValidationError) -> JSONResponse:
    # Par défaut, FastAPI renvoie dans le 422 la valeur saisie (`input`) : un mot de passe trop
    # long ou mal placé repartirait dans la réponse, et finirait dans tout outil qui enregistre
    # les réponses (proxy, APM, suivi d'erreurs du front). On ne garde que l'endroit et le motif.
    errors = [{k: e[k] for k in ("type", "loc", "msg") if k in e} for e in exc.errors()]
    return JSONResponse({"detail": jsonable_encoder(errors)}, status_code=422)


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
        app.state.auth = _auth_state(settings, rules)
        yield
        app.state.jikan.close()
        engine.dispose()

    app = FastAPI(
        title="Tsuzuku API",
        version="0.7.0",
        description="Catalogue, saison en cours, comptes et listes, recommandations et risque "
        "de drop.",
        lifespan=lifespan,
    )
    # CORS restreint au front (SPEC § 7) : jamais « * ». Avec allow_credentials, « * » ferait
    # renvoyer l'origine de N'IMPORTE QUEL site, qui pourrait alors lire /me/export avec la
    # session de l'utilisateur : refusé au démarrage plutôt que de compter sur la config.
    if any(o.strip() == "*" for o in settings.cors_origins):
        raise ValueError("CORS_ORIGINS ne doit pas contenir « * » (cookies de session)")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        # Le cookie de session doit accompagner les appels du front (autre origine en dev).
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["Content-Type"],
    )
    if settings.proxy_secret is not None:
        # Ajouté APRÈS CORS : il s'exécute donc avant lui (Starlette empile à l'envers).
        app.add_middleware(TrustedProxyMiddleware, secret=settings.proxy_secret.get_secret_value())
    app.add_exception_handler(OperationalError, _database_unavailable)
    app.add_exception_handler(RequestValidationError, _invalid_request)
    for router in (health.router, media.router, trending.router, demo.router, auth.router,
                   me.router, users.router):  # fmt: skip
        app.include_router(router)
    return app
