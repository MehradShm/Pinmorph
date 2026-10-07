from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import AwareDatetime, ValidationError

from app.api import pin_out
from app.auth import DB, OptionalUser
from app.models import utcnow
from app.schemas import PinPage
from app.search.service import SearchQuery

router = APIRouter(prefix="/api/search")


class SearchPage(PinPage):
    model_versions: dict[str, str]


def search_query(
    q: Annotated[str, Query(min_length=2, max_length=200)],
    owner_id: Annotated[str | None, Query(min_length=36, max_length=36)] = None,
    provenance: Annotated[str | None, Query(max_length=40)] = None,
    created_after: AwareDatetime | None = None,
    created_before: AwareDatetime | None = None,
) -> SearchQuery:
    try:
        return SearchQuery(
            q=q,
            owner_id=owner_id,
            provenance=provenance,
            created_after=created_after,
            created_before=created_before,
        )
    except ValidationError as exc:
        raise HTTPException(422, "Provide search words and valid filters/date range") from exc


@router.get("/pins", response_model=SearchPage)
def search_pins(
    request: Request,
    db: DB,
    user: OptionalUser,
    query: Annotated[SearchQuery, Depends(search_query)],
    limit: Annotated[int, Query(ge=1, le=100)] = 30,
    cursor: Annotated[str | None, Query(max_length=600)] = None,
):
    backend = request.app.state.search_backend
    try:
        pins, next_cursor = backend.search(db, query, user, utcnow(), limit, cursor)
    except ValueError as exc:
        raise HTTPException(422, "Invalid cursor for this search") from exc
    return SearchPage(
        items=[pin_out(pin) for pin in pins],
        next_cursor=next_cursor,
        request_id=request.state.request_id,
        model_versions={"search": backend.version},
    )


@router.get("/suggest")
def suggest(
    request: Request,
    db: DB,
    user: OptionalUser,
    query: Annotated[SearchQuery, Depends(search_query)],
    limit: Annotated[int, Query(ge=1, le=10)] = 6,
):
    backend = request.app.state.search_backend
    return {
        "items": backend.suggest(db, query, user, utcnow(), limit),
        "request_id": request.state.request_id,
        "model_versions": {"search": backend.version},
    }
