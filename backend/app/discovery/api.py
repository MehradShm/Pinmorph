from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from pydantic import ValidationError

from app.auth import DB, CurrentUser, check_origin
from app.discovery.crop import CropBox, prepare_crop
from app.feed.contracts import FeedContext
from app.media import InvalidImage
from app.models import utcnow
from app.social.policy import visible_pin

router = APIRouter(prefix="/api")


def context(request, user, surface, limit):
    now = utcnow()
    return FeedContext(request.state.request_id, user.id, now, now, limit=limit, surface=surface)


@router.get("/feed/following")
def following(
    request: Request,
    db: DB,
    user: CurrentUser,
    limit: Annotated[int, Query(ge=1, le=100)] = 30,
):
    return request.app.state.discovery_services.following_source.retrieve(
        db, context(request, user, "following", limit)
    )


@router.get("/pins/{pin_id}/related")
def related(
    pin_id: str,
    request: Request,
    db: DB,
    user: CurrentUser,
    limit: Annotated[int, Query(ge=1, le=100)] = 30,
):
    visible_pin(db, pin_id, user)
    return request.app.state.discovery_services.related_source.retrieve(
        db, context(request, user, "related", limit), pin_id
    )


@router.post("/lens", dependencies=[Depends(check_origin)])
def lens(
    request: Request,
    db: DB,
    user: CurrentUser,
    image: Annotated[UploadFile, File()],
    crop_box: Annotated[str, Form(max_length=300)] = "{}",
    limit: Annotated[int, Form(ge=1, le=100)] = 30,
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
    return request.app.state.discovery_services.lens_service.search(
        db, context(request, user, "lens", limit), crop
    )
