"""One visibility policy for public reads and later candidate sources."""

from fastapi import HTTPException
from sqlalchemy import and_, exists, or_, select
from sqlalchemy.orm import Session

from app.models import Board, Pin, User, utcnow
from app.social.models import UserBlock, UserMute


def blocked(db: Session, first: str, second: str) -> bool:
    return bool(
        db.scalar(
            select(
                exists().where(
                    or_(
                        and_(UserBlock.blocker_id == first, UserBlock.blocked_id == second),
                        and_(UserBlock.blocker_id == second, UserBlock.blocked_id == first),
                    )
                )
            )
        )
    )


def visible_owner(owner_column, viewer: User | None, *, include_muted: bool = False):
    if viewer is None:
        return True
    forbidden = (
        select(UserBlock.blocked_id)
        .where(UserBlock.blocker_id == viewer.id)
        .union(select(UserBlock.blocker_id).where(UserBlock.blocked_id == viewer.id))
    )
    conditions = [owner_column.not_in(forbidden)]
    if include_muted:
        conditions.append(
            owner_column.not_in(select(UserMute.muted_id).where(UserMute.muter_id == viewer.id))
        )
    return or_(owner_column.is_(None), and_(*conditions))


def visible_board(db: Session, board_id: str, viewer: User | None) -> Board:
    board = db.get(Board, board_id)
    if (
        board is None
        or (board.is_secret and (viewer is None or board.owner_id != viewer.id))
        or (viewer is not None and blocked(db, viewer.id, board.owner_id))
    ):
        raise HTTPException(404, "Board not found")
    return board


def visible_pin(db: Session, pin_id: str, viewer: User | None) -> Pin:
    pin = db.get(Pin, pin_id)
    if (
        pin is None
        or (viewer and pin.owner_id and blocked(db, viewer.id, pin.owner_id))
        or (
            (pin.status != "ready" or pin.available_at > utcnow())
            and (viewer is None or pin.owner_id != viewer.id)
        )
    ):
        raise HTTPException(404, "Pin not found")
    return pin
