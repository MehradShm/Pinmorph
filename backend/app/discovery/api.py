from typing import Annotated

import httpx
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from pydantic import ValidationError

from app.auth import DB, CurrentUser, check_origin
from app.discovery.crop import CropBox, prepare_crop
from app.feed.contracts import FeedContext, RankedCandidate
from app.feed.schemas import FeedPage
from app.feed.service import page_candidates
from app.media import InvalidImage
from app.ml.baselines import RecencyRanker
from app.models import utcnow
from app.social.policy import visible_pin

router = APIRouter(prefix="/api")


def context(request, user, surface, limit, cursor=None):
    now = utcnow()
    return FeedContext(
        request.state.request_id, user.id, now, now, limit=limit, cursor=cursor, surface=surface
    )


@router.get("/feed/following", response_model=FeedPage)
def following(
    request: Request,
    db: DB,
    user: CurrentUser,
    limit: Annotated[int, Query(ge=1, le=100)] = 30,
    cursor: Annotated[str | None, Query(max_length=2048)] = None,
):
    ctx = context(request, user, "following", limit, cursor)
    services = request.app.state.discovery_services
    source = services.following_source
    rows = RecencyRanker().rank(source.retrieve(db, ctx), ctx)
    return page_candidates(
        db,
        ctx,
        rows,
        {"candidate_source": source.version, "ranker": RecencyRanker.version},
        services.config.version,
    )


@router.get("/pins/{pin_id}/related", response_model=FeedPage)
def related(
    pin_id: str,
    request: Request,
    db: DB,
    user: CurrentUser,
    limit: Annotated[int, Query(ge=1, le=100)] = 30,
    cursor: Annotated[str | None, Query(max_length=2048)] = None,
):
    visible_pin(db, pin_id, user)
    ctx = context(request, user, "related", limit, cursor)
    services = request.app.state.discovery_services
    source = services.related_source
    candidates = source.retrieve(db, ctx, pin_id)
    rows = [RankedCandidate(c, c.retrieval_score or 0, c.retrieval_score or 0) for c in candidates]
    return page_candidates(
        db,
        ctx,
        rows,
        {"candidate_source": source.version, "ranker": "ranker:retrieval-score:v1"},
        services.config.version,
        details={"context_pin_id": pin_id},
        feature_schema="features:related:v1",
    )


@router.post("/lens", response_model=FeedPage, dependencies=[Depends(check_origin)])
def lens(
    request: Request,
    db: DB,
    user: CurrentUser,
    image: Annotated[UploadFile, File()],
    crop_box: Annotated[str, Form(max_length=300)] = "{}",
    limit: Annotated[int, Form(ge=1, le=100)] = 30,
    cursor: Annotated[str | None, Form(max_length=2048)] = None,
):
    try:
        box = CropBox.model_validate_json(crop_box)
        crop = prepare_crop(
            image.file.read(request.app.state.settings.upload_max_bytes + 1),
            box,
            request.app.state.settings,
        )
    except (ValidationError, InvalidImage) as exc:
        raise HTTPException(422, "Provide a valid image and crop coordinates") from exc
    ctx = context(request, user, "lens", limit, cursor)
    services = request.app.state.discovery_services
    try:
        candidates = services.lens_service.search(db, ctx, crop)
    except (httpx.HTTPError, OSError) as exc:
        raise HTTPException(503, "Local Lens encoder unavailable; retry shortly") from exc
    rows = [RankedCandidate(c, c.retrieval_score or 0, c.retrieval_score or 0) for c in candidates]
    return page_candidates(
        db,
        ctx,
        rows,
        {
            "lens": services.lens_service.version,
            "embedder": services.crop_embedder.version,
            "retriever": services.config.lens_retriever,
        },
        services.config.version,
        details={
            "crop_sha256": crop.crop_sha256,
            "crop_policy": crop.policy_version,
            "pool_size": services.config.lens_pool_size,
        },
        feature_schema="features:lens:v1",
    )
