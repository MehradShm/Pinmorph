import base64
import json
from datetime import datetime
from typing import Annotated, Literal

from botocore.exceptions import ClientError
from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
)
from fastapi.responses import StreamingResponse
from pydantic import ValidationError
from sqlalchemy import and_, func, or_, select
from sqlalchemy.exc import IntegrityError

from app.auth import (
    COOKIE_NAME,
    DB,
    CurrentUser,
    OptionalUser,
    check_origin,
    password_hasher,
    start_session,
    token_digest,
    verify_password,
)
from app.media import InvalidImage, enqueue_pin, validate_image
from app.models import AuthSession, Board, Pin, Save, User, new_id, utcnow
from app.schemas import BoardInput, Credentials, PinMetadata, PinOut, PinPage, Signup, UserOut

router = APIRouter(prefix="/api")
mutations = [Depends(check_origin)]


def pin_out(pin: Pin) -> PinOut:
    return PinOut(
        id=pin.id,
        title=pin.title,
        description=pin.description,
        source_url=pin.source_url,
        owner_id=pin.owner_id,
        provenance=pin.provenance,
        status=pin.status,
        processing_error=pin.processing_error,
        width=pin.width,
        height=pin.height,
        dominant_color=pin.dominant_color,
        image_url=f"/api/media/{pin.id}/display.jpg" if pin.status == "ready" else None,
        thumbnail_url=f"/api/media/{pin.id}/thumb.jpg" if pin.status == "ready" else None,
        created_at=pin.created_at,
    )


@router.post("/auth/signup", response_model=UserOut, status_code=201, dependencies=mutations)
def signup(body: Signup, request: Request, response: Response, db: DB):
    user = User(
        email=body.email,
        display_name=body.display_name,
        password_hash=password_hasher.hash(body.password),
    )
    db.add(user)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "An account with this email already exists") from exc
    start_session(request, response, db, user)
    return user


@router.post("/auth/login", response_model=UserOut, dependencies=mutations)
def login(body: Credentials, request: Request, response: Response, db: DB):
    user = db.scalar(select(User).where(User.email == body.email))
    if not verify_password(user.password_hash if user else None, body.password):
        raise HTTPException(401, "Email or password is incorrect")
    start_session(request, response, db, user)
    return user


@router.get("/auth/me", response_model=UserOut)
def me(user: CurrentUser, response: Response):
    response.headers["Cache-Control"] = "no-store"
    return user


@router.post("/auth/logout", status_code=204, dependencies=mutations)
def logout(request: Request, response: Response, db: DB):
    token = request.cookies.get(COOKIE_NAME)
    auth_session = db.get(AuthSession, token_digest(token)) if token else None
    if auth_session:
        db.delete(auth_session)
        db.commit()
    response.delete_cookie(COOKIE_NAME, path="/api")


def cursor_value(value: str | None) -> tuple[datetime, str] | None:
    if value is None:
        return None
    try:
        timestamp, pin_id = json.loads(base64.urlsafe_b64decode(value.encode()))
        timestamp = datetime.fromisoformat(timestamp)
        if timestamp.tzinfo is None or not isinstance(pin_id, str) or len(pin_id) != 36:
            raise ValueError
        return timestamp, pin_id
    except (ValueError, TypeError, UnicodeError) as exc:
        raise HTTPException(422, "Invalid catalog cursor") from exc


def list_page(
    statement, timestamp_column, request: Request, db: DB, limit: int, cursor: str | None
) -> PinPage:
    position = cursor_value(cursor)
    if position:
        timestamp, pin_id = position
        statement = statement.where(
            or_(timestamp_column < timestamp, and_(timestamp_column == timestamp, Pin.id < pin_id))
        )
    rows = db.execute(
        statement.order_by(timestamp_column.desc(), Pin.id.desc()).limit(limit + 1)
    ).all()
    next_cursor = None
    if len(rows) > limit:
        last_pin, last_time = rows[limit - 1]
        next_cursor = base64.urlsafe_b64encode(
            json.dumps([last_time.isoformat(), last_pin.id]).encode()
        ).decode()
    return PinPage(
        items=[pin_out(row[0]) for row in rows[:limit]],
        next_cursor=next_cursor,
        request_id=request.state.request_id,
    )


@router.get("/pins", response_model=PinPage)
def catalog(
    request: Request,
    db: DB,
    limit: Annotated[int, Query(ge=1, le=100)] = 30,
    cursor: Annotated[str | None, Query(max_length=300)] = None,
):
    # Plain catalog pagination. Recommendation ordering/attribution arrives in Phase 2.
    statement = select(Pin, Pin.created_at).where(
        Pin.status == "ready", Pin.available_at <= utcnow()
    )
    return list_page(statement, Pin.created_at, request, db, limit, cursor)


@router.get("/pins/mine", response_model=PinPage)
def my_pins(
    request: Request,
    user: CurrentUser,
    db: DB,
    limit: Annotated[int, Query(ge=1, le=100)] = 30,
    cursor: Annotated[str | None, Query(max_length=300)] = None,
):
    statement = select(Pin, Pin.created_at).where(Pin.owner_id == user.id)
    return list_page(statement, Pin.created_at, request, db, limit, cursor)


@router.post("/pins", response_model=PinOut, status_code=202, dependencies=mutations)
def upload_pin(
    request: Request,
    db: DB,
    user: CurrentUser,
    image: Annotated[UploadFile, File()],
    title: Annotated[str, Form(max_length=200)],
    description: Annotated[str, Form(max_length=2000)] = "",
    source_url: Annotated[str, Form(max_length=2000)] = "",
):
    try:
        metadata = PinMetadata(title=title, description=description, source_url=source_url or None)
    except ValidationError as exc:
        raise HTTPException(422, "Provide a title and a valid http(s) source URL") from exc
    settings = request.app.state.settings
    data = image.file.read(settings.upload_max_bytes + 1)
    try:
        validate_image(data, settings)
    except InvalidImage as exc:
        raise HTTPException(422, str(exc)) from exc
    pin_id = new_id()
    key = f"pins/{pin_id}/original"
    request.app.state.storage.put_object(
        Bucket=settings.s3_bucket, Key=key, Body=data, ContentType="application/octet-stream"
    )
    pin = Pin(
        id=pin_id,
        owner_id=user.id,
        title=metadata.title,
        description=metadata.description,
        source_url=str(metadata.source_url) if metadata.source_url else None,
        original_key=key,
    )
    db.add(pin)
    try:
        db.commit()
    except Exception:
        db.rollback()
        request.app.state.storage.delete_object(Bucket=settings.s3_bucket, Key=key)
        raise
    try:
        enqueue_pin(db, request.app.state.queue, pin, request.state.request_id)
    except Exception as exc:
        raise HTTPException(
            503, {"message": "Processing queue unavailable; retry from Uploads", "pin_id": pin.id}
        ) from exc
    db.refresh(pin)
    return pin_out(pin)


@router.get("/pins/{pin_id}", response_model=PinOut)
def pin_detail(pin_id: str, db: DB, user: OptionalUser):
    pin = db.get(Pin, pin_id)
    if not pin or (
        (pin.status != "ready" or pin.available_at > utcnow())
        and (not user or pin.owner_id != user.id)
    ):
        raise HTTPException(404, "Pin not found")
    return pin_out(pin)


@router.post("/pins/{pin_id}/retry", response_model=PinOut, status_code=202, dependencies=mutations)
def retry_pin(pin_id: str, request: Request, db: DB, user: CurrentUser):
    pin = db.scalar(select(Pin).where(Pin.id == pin_id).with_for_update())
    if not pin or pin.owner_id != user.id:
        raise HTTPException(404, "Pin not found")
    if pin.status != "failed":
        raise HTTPException(409, "Only failed uploads can be retried")
    try:
        enqueue_pin(db, request.app.state.queue, pin, request.state.request_id)
    except Exception as exc:
        raise HTTPException(503, "Processing queue unavailable") from exc
    return pin_out(pin)


@router.get("/media/{pin_id}/{variant}.jpg")
def media(pin_id: str, variant: Literal["thumb", "display"], request: Request, db: DB):
    pin = db.get(Pin, pin_id)
    if (
        not pin
        or pin.status != "ready"
        or pin.available_at > utcnow()
        or variant not in pin.variants
    ):
        raise HTTPException(404, "Image not found")
    try:
        result = request.app.state.storage.get_object(
            Bucket=request.app.state.settings.s3_bucket, Key=pin.variants[variant]["key"]
        )
    except ClientError as exc:
        if exc.response["Error"]["Code"] in {"NoSuchKey", "404"}:
            raise HTTPException(404, "Image not found") from exc
        raise HTTPException(503, "Image storage unavailable") from exc

    def chunks():
        try:
            yield from result["Body"].iter_chunks(chunk_size=65536)
        finally:
            result["Body"].close()

    return StreamingResponse(
        chunks(),
        media_type="image/jpeg",
        headers={
            "Cache-Control": "public, max-age=31536000, immutable",
            "X-Content-Type-Options": "nosniff",
        },
    )


def owned_board(db, board_id: str, user: User) -> Board:
    board = db.get(Board, board_id)
    if not board or board.owner_id != user.id:
        raise HTTPException(404, "Board not found")
    return board


@router.get("/boards")
def boards(db: DB, user: CurrentUser):
    rows = db.execute(
        select(Board, func.count(Save.id))
        .outerjoin(Save)
        .where(Board.owner_id == user.id)
        .group_by(Board.id)
        .order_by(Board.created_at.desc())
    ).all()
    return [{"id": board.id, "name": board.name, "pin_count": count} for board, count in rows]


@router.post("/boards", status_code=201, dependencies=mutations)
def create_board(body: BoardInput, db: DB, user: CurrentUser):
    board = Board(owner_id=user.id, name=body.name)
    db.add(board)
    db.commit()
    return {"id": board.id, "name": board.name, "pin_count": 0}


@router.get("/boards/{board_id}/pins", response_model=PinPage)
def board_pins(
    board_id: str,
    request: Request,
    db: DB,
    user: CurrentUser,
    limit: Annotated[int, Query(ge=1, le=100)] = 30,
    cursor: Annotated[str | None, Query(max_length=300)] = None,
):
    owned_board(db, board_id, user)
    statement = (
        select(Pin, Save.created_at)
        .join(Save)
        .where(Save.board_id == board_id, Pin.status == "ready", Pin.available_at <= utcnow())
    )
    return list_page(statement, Save.created_at, request, db, limit, cursor)


@router.post("/boards/{board_id}/pins/{pin_id}", dependencies=mutations)
def save_pin(board_id: str, pin_id: str, db: DB, user: CurrentUser):
    owned_board(db, board_id, user)
    pin = db.get(Pin, pin_id)
    if not pin or pin.status != "ready" or pin.available_at > utcnow():
        raise HTTPException(404, "Ready pin not found")
    save = Save(board_id=board_id, pin_id=pin_id)
    db.add(save)
    try:
        db.commit()
    except IntegrityError:
        # The unique constraint handles concurrent/retried saves without inflating counts.
        db.rollback()
        save = db.scalar(select(Save).where(Save.board_id == board_id, Save.pin_id == pin_id))
        if save is None:
            raise
    return {"id": save.id, "board_id": board_id, "pin_id": pin_id}


@router.delete("/boards/{board_id}/pins/{pin_id}", status_code=204, dependencies=mutations)
def unsave_pin(board_id: str, pin_id: str, db: DB, user: CurrentUser):
    owned_board(db, board_id, user)
    save = db.scalar(select(Save).where(Save.board_id == board_id, Save.pin_id == pin_id))
    if save:
        db.delete(save)
        db.commit()
