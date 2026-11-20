"""Inscription, connexion, déconnexion (phase 7, ADR 008).

La session est un JWT dans un cookie httpOnly + Secure + SameSite=Lax :
- httpOnly : le JavaScript de la page ne peut pas le lire (un script injecté ne le vole pas) ;
- Secure : jamais envoyé en clair (HTTPS seulement) ;
- SameSite=Lax : un autre site ne peut pas déclencher un POST/PUT/DELETE avec ce cookie (CSRF).
"""

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.orm import Session

from app.api.deps import AuthState, get_auth
from app.core.security import COOKIE_NAME, InvalidToken, create_token, decode_token
from app.db.app_models import User
from app.db.session import get_session
from app.schemas.auth import LoginRequest, RegisterRequest, UserOut
from app.services import auth_service

router = APIRouter(prefix="/auth", tags=["comptes"])
logger = logging.getLogger("tsuzuku_api")

Auth = Annotated[AuthState, Depends(get_auth)]
DbSession = Annotated[Session, Depends(get_session)]


def _client_ip(request: Request) -> str:
    # Derrière un proxy (Cloud Run, phase 11), ce sera l'IP du proxy : à revoir alors (ADR 008).
    return request.client.host if request.client else "unknown"


def _too_many(retry_after: int) -> HTTPException:
    return HTTPException(status.HTTP_429_TOO_MANY_REQUESTS,
                         "Trop de tentatives, réessaie plus tard",
                         headers={"Retry-After": str(retry_after)})  # fmt: skip


def _open_session(response: Response, auth: AuthState, user: User) -> None:
    token = create_token(user.id, user.token_version, auth.secret, auth.rules.token_ttl_hours)
    response.set_cookie(
        COOKIE_NAME, token, max_age=auth.rules.token_ttl_hours * 3600, path="/",
        httponly=True, secure=auth.cookie_secure, samesite="lax",
    )  # fmt: skip


def close_session(response: Response, auth: AuthState) -> None:
    response.delete_cookie(COOKIE_NAME, path="/", httponly=True,
                           secure=auth.cookie_secure, samesite="lax")  # fmt: skip


@router.post("/register", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def register(
    body: RegisterRequest, request: Request, response: Response, auth: Auth, session: DbSession
) -> User:
    # Chaque essai compte (réussi ou non) : limite la création de comptes en masse.
    wait = auth.register_limiter.acquire(f"ip:{_client_ip(request)}")
    if wait:
        raise _too_many(wait)
    try:
        user = auth_service.register(session, auth.hasher, auth.rules, body)
    except auth_service.WeakPassword as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from None
    except auth_service.AccountExists:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "Cet email ou ce pseudo est déjà utilisé") from None  # fmt: skip
    _open_session(response, auth, user)
    return user


@router.post("/login", response_model=UserOut)
def login(
    body: LoginRequest, request: Request, response: Response, auth: Auth, session: DbSession
) -> User:
    # Deux compteurs : par IP (un attaquant qui essaie beaucoup d'emails) et par email (un
    # compte visé depuis plusieurs IP). L'essai est réservé AVANT argon2 (atomique : une rafale
    # simultanée ne passe pas), puis rendu si la connexion réussit : seuls les échecs comptent.
    ip_key, email_key = f"ip:{_client_ip(request)}", f"email:{body.email}"
    wait = auth.login_limiter.acquire(ip_key, email_key)
    if wait:
        logger.warning("Connexion bloquée par la limite de débit")
        raise _too_many(wait)
    user = auth_service.authenticate(session, auth.hasher, body.email, body.password)
    if user is None:
        # Même message pour « email inconnu » et « mauvais mot de passe ».
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Email ou mot de passe incorrect")
    auth.login_limiter.release(ip_key)
    auth.login_limiter.reset(email_key)
    _open_session(response, auth, user)
    return user


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(request: Request, auth: Auth, session: DbSession) -> Response:
    token = request.cookies.get(COOKIE_NAME)
    if token:
        try:
            user_id, version = decode_token(token, auth.secret)
        except InvalidToken:
            pass  # jeton déjà invalide : rien à révoquer, on efface juste le cookie
        else:
            user = session.get(User, user_id)
            if user is not None and user.token_version == version:
                # Révoque CE jeton et toutes les autres sessions du compte (ADR 008).
                auth_service.revoke_sessions(session, user_id)
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    close_session(response, auth)
    return response
