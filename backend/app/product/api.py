from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator
from sqlalchemy import func, select

from app.auth import DB, CurrentUser, OptionalUser, check_origin
from app.models import Pin, User, utcnow
from app.product.digests import deliver_pending, prepare_digest
from app.product.models import Comment, EmailOutbox, HiddenPin, Reaction, SafetyReport, UserSettings
from app.product.url_import import InvalidImport, fetch_image
from app.social.api import lock_pair, notify
from app.social.policy import visible_owner, visible_pin

router = APIRouter(prefix="/api")
mutations = [Depends(check_origin)]
INTERESTS = ("fashion", "home", "food", "travel", "art", "nature", "architecture", "design")


class PreferencesInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    interests: list[str] = Field(default_factory=list, max_length=8)
    onboarding_complete: bool = True
    email_digest: bool = False

    @field_validator("interests")
    @classmethod
    def validate_interests(cls, values):
        if len(set(values)) != len(values) or any(v not in INTERESTS for v in values):
            raise ValueError("Choose unique supported interests")
        return values


def preferences_out(row):
    return {
        "interests": row.interests if row else [],
        "onboarding_complete": row.onboarding_complete if row else False,
        "email_digest": row.email_digest if row else False,
        "available_interests": INTERESTS,
    }


@router.get("/settings")
def preferences(db: DB, user: CurrentUser):
    return preferences_out(db.get(UserSettings, user.id))


@router.put("/settings", dependencies=mutations)
def update_preferences(body: PreferencesInput, db: DB, user: CurrentUser):
    db.scalar(select(User).where(User.id == user.id).with_for_update())
    row = db.get(UserSettings, user.id)
    if not row:
        row = UserSettings(user_id=user.id)
        db.add(row)
    row.interests = body.interests
    row.onboarding_complete = body.onboarding_complete
    row.email_digest = body.email_digest
    row.updated_at = utcnow()
    db.commit()
    return preferences_out(row)


class CommentInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    body: str = Field(min_length=1, max_length=1000)

    @field_validator("body")
    @classmethod
    def clean(cls, value):
        if not value.strip():
            raise ValueError("Write a comment")
        return value.strip()


def comment_out(row, name):
    return {
        "id": row.id,
        "user_id": row.user_id,
        "display_name": name,
        "body": row.body,
        "created_at": row.created_at,
    }


@router.get("/pins/{pin_id}/comments")
def comments(
    pin_id: str,
    db: DB,
    user: OptionalUser,
    limit: Annotated[int, Query(ge=1, le=100)] = 30,
    cursor: Annotated[str | None, Query(min_length=36, max_length=36)] = None,
):
    visible_pin(db, pin_id, user)
    statement = (
        select(Comment, User.display_name)
        .join(User, User.id == Comment.user_id)
        .where(Comment.pin_id == pin_id, visible_owner(Comment.user_id, user, include_muted=True))
    )
    if cursor:
        statement = statement.where(Comment.id > cursor)
    rows = db.execute(statement.order_by(Comment.id).limit(limit + 1)).all()
    return {
        "items": [comment_out(c, n) for c, n in rows[:limit]],
        "next_cursor": rows[limit - 1][0].id if len(rows) > limit else None,
    }


@router.post("/pins/{pin_id}/comments", status_code=201, dependencies=mutations)
def add_comment(pin_id: str, body: CommentInput, db: DB, user: CurrentUser):
    pin = visible_pin(db, pin_id, user)
    if pin.status != "ready":
        raise HTTPException(409, "Pin is not available")
    if pin.owner_id and pin.owner_id != user.id:
        lock_pair(db, user.id, pin.owner_id)
        visible_pin(db, pin_id, user)
    row = Comment(user_id=user.id, pin_id=pin_id, body=body.body)
    db.add(row)
    if pin.owner_id:
        notify(db, pin.owner_id, user.id, "comment")
    db.commit()
    return comment_out(row, user.display_name)


@router.delete("/comments/{comment_id}", status_code=204, dependencies=mutations)
def remove_comment(comment_id: str, db: DB, user: CurrentUser):
    row = db.get(Comment, comment_id)
    if not row or (row.user_id != user.id and not user.is_moderator):
        raise HTTPException(404, "Comment not found")
    db.delete(row)
    db.commit()


@router.get("/pins/{pin_id}/reaction")
def reaction(pin_id: str, db: DB, user: OptionalUser):
    visible_pin(db, pin_id, user)
    count = db.scalar(
        select(func.count())
        .select_from(Reaction)
        .where(Reaction.pin_id == pin_id, visible_owner(Reaction.user_id, user, include_muted=True))
    )
    return {"count": count, "liked": bool(user and db.get(Reaction, (user.id, pin_id)))}


@router.put("/pins/{pin_id}/reaction", dependencies=mutations)
def like(pin_id: str, db: DB, user: CurrentUser):
    pin = visible_pin(db, pin_id, user)
    if pin.owner_id and pin.owner_id != user.id:
        lock_pair(db, user.id, pin.owner_id)
    else:
        db.scalar(select(User).where(User.id == user.id).with_for_update())
    pin = visible_pin(db, pin_id, user)
    if not db.get(Reaction, (user.id, pin_id)):
        db.add(Reaction(user_id=user.id, pin_id=pin_id))
        if pin.owner_id:
            notify(db, pin.owner_id, user.id, "reaction")
    db.commit()
    return reaction(pin_id, db, user)


@router.delete("/pins/{pin_id}/reaction", status_code=204, dependencies=mutations)
def unlike(pin_id: str, db: DB, user: CurrentUser):
    row = db.get(Reaction, (user.id, pin_id))
    if row:
        db.delete(row)
    db.commit()


@router.put("/pins/{pin_id}/hide", status_code=204, dependencies=mutations)
def hide(pin_id: str, db: DB, user: CurrentUser):
    visible_pin(db, pin_id, user)
    db.scalar(select(User).where(User.id == user.id).with_for_update())
    if not db.get(HiddenPin, (user.id, pin_id)):
        db.add(HiddenPin(user_id=user.id, pin_id=pin_id))
    db.commit()


@router.get("/settings/hidden")
def hidden(db: DB, user: CurrentUser):
    return {
        "items": [
            {"id": pin.id, "title": pin.title}
            for pin in db.scalars(
                select(Pin)
                .join(HiddenPin, HiddenPin.pin_id == Pin.id)
                .where(HiddenPin.user_id == user.id, visible_owner(Pin.owner_id, user))
                .limit(100)
            )
        ]
    }


@router.delete("/pins/{pin_id}/hide", status_code=204, dependencies=mutations)
def unhide(pin_id: str, db: DB, user: CurrentUser):
    row = db.get(HiddenPin, (user.id, pin_id))
    if row:
        db.delete(row)
    db.commit()


class ReportInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str = Field(min_length=3, max_length=1000)

    @field_validator("reason")
    @classmethod
    def clean_reason(cls, value):
        if len(value.strip()) < 3:
            raise ValueError("Describe the reason for reporting")
        return value.strip()


@router.post("/pins/{pin_id}/report", status_code=201, dependencies=mutations)
def report(pin_id: str, body: ReportInput, db: DB, user: CurrentUser):
    visible_pin(db, pin_id, user)
    db.scalar(select(User).where(User.id == user.id).with_for_update())
    row = db.scalar(
        select(SafetyReport).where(SafetyReport.user_id == user.id, SafetyReport.pin_id == pin_id)
    )
    if not row:
        row = SafetyReport(user_id=user.id, pin_id=pin_id, reason=body.reason.strip())
        db.add(row)
    db.commit()
    return {"id": row.id, "status": row.status}


@router.get("/moderation/reports")
def moderation_reports(
    db: DB,
    user: CurrentUser,
    cursor: Annotated[str | None, Query(min_length=36, max_length=36)] = None,
):
    if not user.is_moderator:
        raise HTTPException(403, "Moderator access required")
    statement = (
        select(SafetyReport, Pin.title)
        .join(Pin, Pin.id == SafetyReport.pin_id)
        .where(SafetyReport.status == "open")
    )
    if cursor:
        statement = statement.where(SafetyReport.id > cursor)
    rows = db.execute(statement.order_by(SafetyReport.id).limit(31)).all()
    return {
        "items": [
            {
                "id": r.id,
                "pin_id": r.pin_id,
                "title": title,
                "reason": r.reason,
                "source": r.source,
                "created_at": r.created_at,
            }
            for r, title in rows[:30]
        ],
        "next_cursor": rows[29][0].id if len(rows) > 30 else None,
    }


class ReviewInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["remove", "restore", "dismiss"]


@router.put("/moderation/reports/{report_id}", dependencies=mutations)
def review(report_id: str, body: ReviewInput, db: DB, user: CurrentUser):
    if not user.is_moderator:
        raise HTTPException(403, "Moderator access required")
    row = db.scalar(select(SafetyReport).where(SafetyReport.id == report_id).with_for_update())
    if not row:
        raise HTTPException(404, "Report not found")
    if row.status == "reviewed":
        if row.action != body.action:
            raise HTTPException(409, "Report already reviewed")
        return {"status": row.status, "action": row.action}
    pin = db.scalar(select(Pin).where(Pin.id == row.pin_id).with_for_update())
    if body.action == "remove":
        pin.status = "removed"
    elif body.action == "restore":
        if not pin.variants:
            raise HTTPException(409, "Media processing must finish before restoring")
        pin.status = "ready"
    row.status, row.action, row.reviewer_id, row.reviewed_at = (
        "reviewed",
        body.action,
        user.id,
        utcnow(),
    )
    db.commit()
    return {"status": row.status, "action": row.action}


class ImportInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    url: HttpUrl
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=2000)

    @field_validator("title")
    @classmethod
    def clean_title(cls, value):
        if not value.strip():
            raise ValueError("A title is required")
        return value.strip()


@router.post("/pins/import", status_code=202, dependencies=mutations)
def import_image(body: ImportInput, request: Request, db: DB, user: CurrentUser):
    from app.api import create_uploaded_pin

    try:
        data = fetch_image(str(body.url), request.app.state.settings)
    except InvalidImport as exc:
        raise HTTPException(422, str(exc)) from exc
    return create_uploaded_pin(request, db, user, data, body.title, body.description, str(body.url))


@router.post("/notifications/digest", status_code=202, dependencies=mutations)
def request_digest(request: Request, db: DB, user: CurrentUser):
    row = prepare_digest(db, user, utcnow())
    db.commit()
    if row and row.status == "pending":
        request.app.state.queue.enqueue(deliver_pending, job_timeout=60)
    return {"outbox_id": row.id if row else None, "status": row.status if row else "no_activity"}


@router.get("/notifications/digests")
def digest_status(db: DB, user: CurrentUser):
    rows = db.scalars(
        select(EmailOutbox)
        .where(EmailOutbox.user_id == user.id)
        .order_by(EmailOutbox.created_at.desc())
        .limit(30)
    )
    return {
        "items": [
            {"id": row.id, "status": row.status, "period": row.period, "attempts": row.attempts}
            for row in rows
        ]
    }


@router.get("/moderation/pins/{pin_id}/image")
def moderation_image(pin_id: str, request: Request, db: DB, user: CurrentUser):
    from fastapi.responses import StreamingResponse

    if not user.is_moderator:
        raise HTTPException(403, "Moderator access required")
    pin = db.get(Pin, pin_id)
    if not pin or "display" not in pin.variants:
        raise HTTPException(404, "Processed image not found")
    response = request.app.state.storage.get_object(
        Bucket=request.app.state.settings.s3_bucket, Key=pin.variants["display"]["key"]
    )

    def chunks():
        try:
            yield from response["Body"].iter_chunks(chunk_size=65536)
        finally:
            response["Body"].close()

    return StreamingResponse(
        chunks(), media_type="image/jpeg", headers={"Cache-Control": "private, no-store"}
    )
