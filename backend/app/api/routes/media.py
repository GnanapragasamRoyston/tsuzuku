from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from sqlalchemy.orm import Session

from app.api.deps import CurrentUser, get_rules
from app.core.config import ApiRules
from app.db.session import get_session
from app.schemas.media import (
    CoverSuggestionIn,
    MediaDetail,
    MediaSummary,
    PopularResponse,
    SearchResponse,
)
from app.services import catalog_service, cover_service

router = APIRouter(prefix="/media", tags=["catalogue"])

Kind = Literal["anime", "manga", "manhwa", "manhua"]


@router.get("/search", response_model=SearchResponse)
def search_media(
    session: Annotated[Session, Depends(get_session)],
    rules: Annotated[ApiRules, Depends(get_rules)],
    q: Annotated[str, Query(min_length=2, max_length=100, description="Texte du titre")],
    kind: Annotated[list[Kind] | None, Query(description="Un ou plusieurs types")] = None,
    limit: Annotated[int | None, Query(ge=1)] = None,
) -> SearchResponse:
    query = q.strip()
    if len(query) < 2:
        # « q=  » passerait min_length puis deviendrait vide : tout le catalogue correspondrait.
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT,
                            "la recherche doit contenir au moins 2 caractères")  # fmt: skip
    limit = min(limit or rules.search_limit_default, rules.search_limit_max)
    items = catalog_service.search(session, query, list(dict.fromkeys(kind or [])), limit)
    return SearchResponse(query=query, items=[MediaSummary.model_validate(m) for m in items])


@router.get("/popular", response_model=PopularResponse)
def popular_media(
    session: Annotated[Session, Depends(get_session)],
    rules: Annotated[ApiRules, Depends(get_rules)],
    kind: Annotated[list[Kind], Query(min_length=1, description="Un ou plusieurs types")],
    limit: Annotated[int | None, Query(ge=1)] = None,
    offset: Annotated[int, Query(ge=0, le=10_000)] = 0,
) -> PopularResponse:
    # Déclarée AVANT /{media_id} : sinon « popular » serait lu comme un identifiant (422).
    limit = min(limit or rules.search_limit_default, rules.search_limit_max)
    items = catalog_service.popular(session, list(dict.fromkeys(kind)), limit, offset)
    return PopularResponse(items=[MediaSummary.model_validate(m) for m in items])


@router.post("/{media_id}/cover-suggestions", status_code=status.HTTP_201_CREATED)
def suggest_cover(
    media_id: Annotated[int, Path(gt=0)],
    body: CoverSuggestionIn,
    user: CurrentUser,
    session: Annotated[Session, Depends(get_session)],
    rules: Annotated[ApiRules, Depends(get_rules)],
) -> dict[str, str]:
    """« Proposer une jaquette » : mise en file de modération (ADR 012), jamais affichée avant
    la validation de Royston."""
    try:
        cover_service.suggest(session, user.id, media_id, body.url, rules)
    except cover_service.InvalidCoverUrl as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from None
    except cover_service.MediaNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Œuvre {media_id} introuvable") from None
    except cover_service.AlreadySuggested:
        raise HTTPException(status.HTTP_409_CONFLICT, "Tu as déjà proposé cette image") from None
    except cover_service.TooManySuggestions:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS,
                            "Trop de propositions aujourd'hui") from None  # fmt: skip
    return {"status": "pending"}


@router.get("/{media_id}", response_model=MediaDetail)
def get_media(
    media_id: Annotated[int, Path(gt=0)],
    session: Annotated[Session, Depends(get_session)],
) -> MediaDetail:
    found = catalog_service.detail(session, media_id)
    if found is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Œuvre {media_id} introuvable")
    media = MediaSummary.model_validate(found["media"]).model_dump()
    m = found["media"]
    return MediaDetail(
        **media,
        synopsis=m.synopsis,
        airing_status=m.airing_status,
        duration_min=m.duration_min,
        creators=list(m.creators or []),
        source=m.source,
        age_rating=m.age_rating,
        genres=found["genres"],
        critical=found["critical"],
        drop_curve=found["drop_curve"],
        latest_stats=found["latest_stats"],
    )
