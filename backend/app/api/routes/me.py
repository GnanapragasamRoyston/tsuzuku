"""Routes du compte connecté : profil, liste, onboarding, recos, risque de drop, RGPD (phase 7).

Les recos et le risque de drop appellent les MÊMES services que le mode démo (phase 5) ; seule
change la source du profil : la liste lue en base au lieu du corps de la requête.
"""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request, Response, status
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.api.deps import (
    AuthState,
    CurrentUser,
    get_auth,
    get_drop_engine,
    get_reco_engine,
    get_rules,
)
from app.api.routes.auth import close_session
from app.core.config import ApiRules
from app.db.session import get_session
from app.schemas.auth import DeleteAccountRequest, MeOut, MeUpdate
from app.schemas.demo import DropRiskResponse, ListStatus, RecoResponse
from app.schemas.me import (
    AccountExport,
    ListEntryOut,
    ListEntryUpdate,
    ListPage,
    OnboardingRequest,
    OnboardingResponse,
)
from app.services import (
    auth_service,
    content_reco_service,
    drop_service,
    list_service,
    reco_service,
)

router = APIRouter(prefix="/me", tags=["mon compte"])

DbSession = Annotated[Session, Depends(get_session)]
Rules = Annotated[ApiRules, Depends(get_rules)]
MediaId = Annotated[int, Path(gt=0)]


# --- Profil et RGPD ------------------------------------------------------------------------------
@router.get("", response_model=MeOut)
def me(user: CurrentUser, session: DbSession) -> dict:
    return auth_service.profile(session, user)


@router.patch("", response_model=MeOut)
def update_me(body: MeUpdate, user: CurrentUser, session: DbSession) -> dict:
    """Réglages du compte : pour l'instant la visibilité du profil public (opt-in, ADR 011)."""
    user.profile_public = body.profile_public
    session.commit()
    return auth_service.profile(session, user)


@router.get("/export", response_model=AccountExport)
def export(user: CurrentUser, session: DbSession) -> JSONResponse:
    data = AccountExport.model_validate(auth_service.export(session, user))
    # Téléchargement d'un fichier (droit à la portabilité), et jamais mis en cache.
    return JSONResponse(
        data.model_dump(mode="json"),
        headers={"Content-Disposition": 'attachment; filename="tsuzuku-export.json"',
                 "Cache-Control": "no-store"},
    )  # fmt: skip


@router.delete("", status_code=status.HTTP_204_NO_CONTENT)
def delete_me(
    body: DeleteAccountRequest,
    user: CurrentUser,
    session: DbSession,
    auth: Annotated[AuthState, Depends(get_auth)],
) -> Response:
    # Mot de passe redemandé : un cookie volé ou une session restée ouverte ne suffit pas à
    # effacer un compte (action irréversible). Essais limités comme la connexion : sinon un cookie
    # volé permettrait de deviner le mot de passe sans limite (et de charger le CPU avec argon2).
    key = f"user:{user.id}"
    wait = auth.login_limiter.acquire(key)
    if wait:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS,
                            "Trop de tentatives, réessaie plus tard",
                            headers={"Retry-After": str(wait)})  # fmt: skip
    if not auth.hasher.verify(user.password_hash, body.password):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Mot de passe incorrect")
    auth.login_limiter.reset(key)
    auth_service.delete_account(session, user)
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    close_session(response, auth)
    return response


# --- Liste ---------------------------------------------------------------------------------------
@router.get("/list", response_model=ListPage)
def get_list(
    user: CurrentUser,
    session: DbSession,
    rules: Rules,
    status_: Annotated[ListStatus | None, Query(alias="status")] = None,
    limit: Annotated[int, Query(ge=1)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> dict:
    if limit > rules.list_page_max:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT,
                            f"limit : {rules.list_page_max} au maximum")  # fmt: skip
    return list_service.page(session, user.id, status_, limit, offset)


@router.get("/list/{media_id}", response_model=ListEntryOut)
def get_entry(media_id: MediaId, user: CurrentUser, session: DbSession) -> dict:
    """Une seule entrée : la fiche œuvre sait si l'œuvre est dans la liste, et où on en est."""
    found = list_service.entry(session, user.id, media_id)
    if found is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Œuvre absente de ta liste")
    return found


@router.post("/list/{media_id}", response_model=ListEntryOut, status_code=status.HTTP_201_CREATED)
def create_entry(
    media_id: MediaId, body: ListEntryUpdate, user: CurrentUser, session: DbSession, rules: Rules
) -> dict:
    """Ajout seul (« Ajouter à ma liste » depuis une reco) : 409 si l'œuvre y est déjà, au lieu
    d'écraser sa progression et sa note comme le ferait un PUT."""
    return _write_entry(session, user.id, media_id, body, rules, create_only=True)


@router.put("/list/{media_id}", response_model=ListEntryOut)
def put_entry(
    media_id: MediaId, body: ListEntryUpdate, user: CurrentUser, session: DbSession, rules: Rules
) -> dict:
    return _write_entry(session, user.id, media_id, body, rules, create_only=False)


def _write_entry(
    session: Session,
    user_id: int,
    media_id: int,
    body: ListEntryUpdate,
    rules: ApiRules,
    create_only: bool,
) -> dict:
    try:
        return list_service.upsert(session, user_id, media_id, body, rules, create_only)
    except list_service.AlreadyInList:
        raise HTTPException(status.HTTP_409_CONFLICT, "Déjà dans ta liste") from None
    except list_service.MediaNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Œuvre {media_id} introuvable") from None
    except list_service.InvalidEntry as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from None
    except list_service.ListFull:
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"liste pleine ({rules.list_max_entries} œuvres au maximum)"
        ) from None


@router.delete("/list/{media_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_entry(media_id: MediaId, user: CurrentUser, session: DbSession) -> Response:
    if not list_service.remove(session, user.id, media_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Œuvre absente de ta liste")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- Onboarding, recos, risque de drop -----------------------------------------------------------
@router.post("/onboarding", response_model=OnboardingResponse)
def onboarding(
    body: OnboardingRequest, user: CurrentUser, session: DbSession, rules: Rules
) -> OnboardingResponse:
    try:
        count = list_service.set_onboarding(session, user.id, body.media_ids, rules)
    except list_service.InvalidEntry as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from None
    return OnboardingResponse(count=count)


@router.get("/recommendations", response_model=RecoResponse)
def recommendations(
    user: CurrentUser,
    session: DbSession,
    rules: Rules,
    request: Request,
    kind: Annotated[list[Literal["anime", "manga", "manhwa", "manhua"]] | None, Query()] = None,
    k: Annotated[int | None, Query(ge=1)] = None,
) -> RecoResponse:
    kinds = sorted(set(kind or ["anime"]))
    if "anime" in kinds and len(kinds) > 1:
        # Deux moteurs différents (ALS pour les animes, contenu pour le reste) : leurs scores ne
        # se comparent pas, on ne les mélange pas dans une même liste.
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT,
                            "animes et mangas se demandent séparément")  # fmt: skip
    liked, exclude = list_service.reco_inputs(session, user.id)
    k = min(k or rules.default_k, rules.max_k)
    if kinds != ["anime"]:
        # Mangas, manhwas, manhuas : pas d'historique d'interactions, recos par le contenu
        # (embeddings, phase 10). Le profil vient de TOUTE la liste (cross-média).
        # Sans le modèle ALS (qu'elles n'utilisent pas) : un ALS absent ne bloque pas les livres.
        result = content_reco_service.recommend(
            session,
            liked,
            kinds,
            k,
            exclude,
            rules.content_default_score,
            rules.content_neutral_score,
            rules.content_popularity_beta,
        )
        return RecoResponse.model_validate(result, from_attributes=True)
    engine = get_reco_engine(request)  # 503 si le modèle ALS manque
    result = reco_service.recommend_for(engine, session, liked, k, exclude_media_ids=exclude)
    return RecoResponse.model_validate(result, from_attributes=True)


@router.get("/drop-risk/{media_id}", response_model=DropRiskResponse)
def drop_risk(
    media_id: MediaId,
    user: CurrentUser,
    session: DbSession,
    engine: Annotated[drop_service.DropEngine, Depends(get_drop_engine)],
) -> DropRiskResponse:
    entries = list_service.drop_inputs(session, user.id)
    try:
        result = drop_service.drop_risk(engine, session, media_id, entries)
    except drop_service.MediaNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Œuvre {media_id} introuvable") from None
    return DropRiskResponse(**result)
