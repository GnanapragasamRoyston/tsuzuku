"""Dépendances FastAPI : accès à l'état chargé au démarrage (règles, modèles, client Jikan),
et compte connecté (phase 7)."""

from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.clients.jikan import JikanClient
from app.core.config import ApiRules, AuthRules
from app.core.rate_limit import SlidingWindowLimiter
from app.core.security import COOKIE_NAME, InvalidToken, PasswordHasher, decode_token
from app.db.app_models import User
from app.db.session import get_session
from app.services.drop_service import DropEngine
from app.services.reco_service import RecoEngine


@dataclass(frozen=True)
class AuthState:
    """Tout ce qu'il faut aux routes de compte, créé une fois au démarrage."""

    secret: str
    rules: AuthRules
    cookie_secure: bool
    hasher: PasswordHasher
    login_limiter: SlidingWindowLimiter
    register_limiter: SlidingWindowLimiter

    @classmethod
    def build(cls, secret: str, rules: AuthRules, cookie_secure: bool) -> "AuthState":
        return cls(
            secret=secret,
            rules=rules,
            cookie_secure=cookie_secure,
            hasher=PasswordHasher(),
            login_limiter=SlidingWindowLimiter(
                rules.login_limit.max_attempts, rules.login_limit.window_s
            ),
            register_limiter=SlidingWindowLimiter(
                rules.register_limit.max_attempts, rules.register_limit.window_s
            ),
        )


def get_auth(request: Request) -> AuthState:
    auth = request.app.state.auth
    if auth is None:
        # Pas de JWT_SECRET : le reste de l'API marche, les comptes sont indisponibles (503).
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Comptes indisponibles")
    return auth


def _unauthorized() -> HTTPException:
    # Même réponse quelle que soit la cause (absent, expiré, révoqué…) : rien à apprendre.
    return HTTPException(status.HTTP_401_UNAUTHORIZED, "Connexion requise")


def get_current_user(
    request: Request,
    auth: Annotated[AuthState, Depends(get_auth)],
    session: Annotated[Session, Depends(get_session)],
) -> User:
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        raise _unauthorized()
    try:
        user_id, token_version = decode_token(token, auth.secret)
    except InvalidToken:
        raise _unauthorized() from None
    user = session.get(User, user_id)
    # token_version différente : jeton émis avant une déconnexion → révoqué.
    if user is None or user.token_version != token_version:
        raise _unauthorized()
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


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
