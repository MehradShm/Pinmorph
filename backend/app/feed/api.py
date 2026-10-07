from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from app.auth import DB, CurrentUser, check_origin
from app.feed.contracts import FeedContext
from app.feed.schemas import FeedPage
from app.logging.schemas import EventInput, EventResult
from app.logging.service import EventConflict, InvalidAttribution
from app.models import utcnow

router = APIRouter(prefix="/api")


def reject_simulation_overrides(request: Request) -> None:
    # Registered run-scoped time/auth is future work; ordinary routes use server UTC.
    if any(name.lower().startswith("x-sim-") for name in request.headers):
        raise HTTPException(422, "Simulator request overrides are not implemented")


@router.get("/feed", response_model=FeedPage)
def home_feed(
    request: Request,
    db: DB,
    user: CurrentUser,
    limit: Annotated[int, Query(ge=1, le=100)] = 30,
    cursor: Annotated[str | None, Query(max_length=2048)] = None,
):
    reject_simulation_overrides(request)
    now = utcnow()
    return request.app.state.feed_service.serve(
        db,
        FeedContext(
            request_id=request.state.request_id,
            user_id=user.id,
            as_of=now,
            received_at=now,
            limit=limit,
            cursor=cursor,
        ),
    )


@router.post("/events", response_model=EventResult, dependencies=[Depends(check_origin)])
def receive_event(event: EventInput, request: Request, db: DB, user: CurrentUser):
    reject_simulation_overrides(request)
    try:
        return request.app.state.event_ingestor.ingest(db, user.id, event, utcnow())
    except EventConflict as exc:
        raise HTTPException(409, "Event ID was reused with different content") from exc
    except InvalidAttribution as exc:
        raise HTTPException(422, "Event does not match this user's served item") from exc
