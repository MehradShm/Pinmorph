from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError

from app.api import list_page, owned_board
from app.auth import DB, CurrentUser, OptionalUser, check_origin
from app.models import Board, BoardSection, Pin, Save, utcnow
from app.schemas import BoardInput, PinPage
from app.social.api import target_user
from app.social.models import BoardFollow
from app.social.policy import visible_board, visible_owner
from app.social.schemas import SectionAssignment, SectionInput

router = APIRouter(prefix="/api")
mutations = [Depends(check_origin)]


def board_out(db, board, viewer):
    return {
        "id": board.id,
        "name": board.name,
        "owner_id": board.owner_id,
        "is_secret": board.is_secret,
        "pin_count": db.scalar(
            select(func.count())
            .select_from(Save)
            .join(Pin)
            .where(
                Save.board_id == board.id,
                Pin.status == "ready",
                Pin.available_at <= utcnow(),
                visible_owner(Pin.owner_id, viewer),
            )
        ),
        "is_following": bool(viewer and db.get(BoardFollow, (viewer.id, board.id))),
    }


@router.get("/profiles/{user_id}/boards")
def public_boards(
    user_id: str,
    db: DB,
    viewer: OptionalUser,
    limit: Annotated[int, Query(ge=1, le=50)] = 30,
    cursor: Annotated[str | None, Query(min_length=36, max_length=36)] = None,
):
    target_user(db, user_id, viewer)
    statement = select(Board).where(Board.owner_id == user_id)
    if viewer is None or viewer.id != user_id:
        statement = statement.where(Board.is_secret.is_(False))
    if cursor:
        statement = statement.where(Board.id > cursor)
    rows = list(db.scalars(statement.order_by(Board.id).limit(limit + 1)))
    return {
        "items": [board_out(db, board, viewer) for board in rows[:limit]],
        "next_cursor": rows[limit - 1].id if len(rows) > limit else None,
    }


@router.get("/profiles/{user_id}/pins", response_model=PinPage)
def profile_pins(
    user_id: str,
    request: Request,
    db: DB,
    viewer: OptionalUser,
    limit: Annotated[int, Query(ge=1, le=100)] = 30,
    cursor: Annotated[str | None, Query(max_length=300)] = None,
):
    target_user(db, user_id, viewer)
    statement = select(Pin, Pin.created_at).where(
        Pin.owner_id == user_id, Pin.status == "ready", Pin.available_at <= utcnow()
    )
    return list_page(statement, Pin.created_at, request, db, limit, cursor)


@router.get("/boards/{board_id}")
def board_detail(board_id: str, db: DB, viewer: OptionalUser):
    return board_out(db, visible_board(db, board_id, viewer), viewer)


@router.put("/boards/{board_id}", dependencies=mutations)
def update_board(board_id: str, body: BoardInput, db: DB, user: CurrentUser):
    board = db.scalar(select(Board).where(Board.id == board_id).with_for_update())
    if board is None or board.owner_id != user.id:
        raise HTTPException(404, "Board not found")
    board.name = body.name
    board.is_secret = body.is_secret
    if body.is_secret:
        db.execute(delete(BoardFollow).where(BoardFollow.board_id == board_id))
    db.commit()
    return board_out(db, board, user)


@router.get("/boards/{board_id}/sections")
def sections(board_id: str, db: DB, viewer: OptionalUser):
    visible_board(db, board_id, viewer)
    return [
        {"id": section.id, "name": section.name}
        for section in db.scalars(
            select(BoardSection)
            .where(BoardSection.board_id == board_id)
            .order_by(BoardSection.name)
        )
    ]


@router.post("/boards/{board_id}/sections", status_code=201, dependencies=mutations)
def create_section(board_id: str, body: SectionInput, db: DB, user: CurrentUser):
    owned_board(db, board_id, user)
    section = BoardSection(board_id=board_id, name=body.name)
    db.add(section)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "A section with this name already exists") from exc
    return {"id": section.id, "name": section.name}


@router.delete("/boards/{board_id}/sections/{section_id}", status_code=204, dependencies=mutations)
def delete_section(board_id: str, section_id: str, db: DB, user: CurrentUser):
    owned_board(db, board_id, user)
    section = db.get(BoardSection, section_id)
    if section is None or section.board_id != board_id:
        raise HTTPException(404, "Section not found")
    # Deleting an organizational section keeps its pins saved in the board.
    db.delete(section)
    db.commit()


@router.put("/boards/{board_id}/pins/{pin_id}/section", dependencies=mutations)
def assign_section(
    board_id: str,
    pin_id: str,
    body: SectionAssignment,
    db: DB,
    user: CurrentUser,
):
    owned_board(db, board_id, user)
    save = db.scalar(
        select(Save).where(Save.board_id == board_id, Save.pin_id == pin_id).with_for_update()
    )
    if save is None:
        raise HTTPException(404, "Saved pin not found")
    if body.section_id is not None:
        section = db.scalar(
            select(BoardSection)
            .where(BoardSection.id == body.section_id, BoardSection.board_id == board_id)
            .with_for_update()
        )
        if section is None:
            raise HTTPException(404, "Section not found")
    save.section_id = body.section_id
    db.commit()
    return {"pin_id": pin_id, "section_id": save.section_id}
