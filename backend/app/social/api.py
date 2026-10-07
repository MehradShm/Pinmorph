"""Thin social features. Product writes are not ML engagement/impression records."""

import base64
import json
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, delete, func, or_, select

from app.api import cursor_value
from app.auth import DB, CurrentUser, OptionalUser, check_origin
from app.models import Board, User, utcnow
from app.social.models import BoardFollow, Notification, UserBlock, UserFollow, UserMute
from app.social.policy import blocked, visible_board, visible_owner
from app.social.schemas import ProfileInput

router = APIRouter(prefix="/api")
mutations = [Depends(check_origin)]
PageLimit = Annotated[int, Query(ge=1, le=50)]
AfterID = Annotated[str | None, Query(min_length=36, max_length=36)]


def profile_out(db, profile: User, viewer: User | None) -> dict:
    # Public profiles never expose email, authentication or import identifiers.
    return {
        "id": profile.id,
        "display_name": profile.display_name,
        "bio": profile.bio,
        "follower_count": db.scalar(
            select(func.count()).select_from(UserFollow).where(UserFollow.followed_id == profile.id)
        ),
        "following_count": db.scalar(
            select(func.count()).select_from(UserFollow).where(UserFollow.follower_id == profile.id)
        ),
        "is_following": bool(viewer and db.get(UserFollow, (viewer.id, profile.id))),
        "is_muted": bool(viewer and db.get(UserMute, (viewer.id, profile.id))),
    }


def target_user(db, target_id: str, viewer: User | None) -> User:
    target = db.get(User, target_id)
    if target is None or (viewer and blocked(db, viewer.id, target.id)):
        raise HTTPException(404, "Profile not found")
    return target


def lock_pair(db, actor_id: str, target_id: str) -> None:
    if actor_id == target_id:
        raise HTTPException(422, "Choose another user")
    # Serialize follows/blocks in one stable lock order, including concurrent retries.
    users = list(
        db.scalars(
            select(User)
            .where(User.id.in_([actor_id, target_id]))
            .order_by(User.id)
            .with_for_update()
        )
    )
    if len(users) != 2:
        raise HTTPException(404, "Profile not found")


def notify(db, recipient: str, actor: str, kind: str, board_id: str | None = None):
    if recipient != actor and db.get(UserMute, (recipient, actor)) is None:
        db.add(Notification(recipient_id=recipient, actor_id=actor, kind=kind, board_id=board_id))


def profile_page(statement, db, viewer, limit, after):
    if after:
        statement = statement.where(User.id > after)
    rows = list(
        db.scalars(
            statement.where(visible_owner(User.id, viewer)).order_by(User.id).limit(limit + 1)
        )
    )
    return {
        "items": [profile_out(db, row, viewer) for row in rows[:limit]],
        "next_cursor": rows[limit - 1].id if len(rows) > limit else None,
    }


@router.get("/profiles")
def find_profiles(
    db: DB,
    viewer: OptionalUser,
    q: Annotated[str, Query(min_length=2, max_length=80)],
    limit: PageLimit = 20,
    cursor: AfterID = None,
):
    query = q.strip().lower()
    if len(query) < 2:
        raise HTTPException(422, "Enter at least two characters")
    return profile_page(
        select(User).where(func.lower(User.display_name).contains(query, autoescape=True)),
        db,
        viewer,
        limit,
        cursor,
    )


@router.patch("/profiles/me", dependencies=mutations)
def edit_profile(body: ProfileInput, db: DB, user: CurrentUser):
    user.display_name = body.display_name
    user.bio = body.bio.strip()
    db.commit()
    return profile_out(db, user, user)


@router.get("/profiles/{user_id}")
def profile(user_id: str, db: DB, viewer: OptionalUser):
    return profile_out(db, target_user(db, user_id, viewer), viewer)


@router.get("/profiles/{user_id}/connections/{relation}")
def profile_relationships(
    user_id: str,
    relation: str,
    db: DB,
    viewer: OptionalUser,
    limit: PageLimit = 20,
    cursor: AfterID = None,
):
    target_user(db, user_id, viewer)
    if relation == "followers":
        statement = (
            select(User)
            .join(UserFollow, UserFollow.follower_id == User.id)
            .where(UserFollow.followed_id == user_id)
        )
    elif relation == "following":
        statement = (
            select(User)
            .join(UserFollow, UserFollow.followed_id == User.id)
            .where(UserFollow.follower_id == user_id)
        )
    else:
        raise HTTPException(404, "Relationship list not found")
    return profile_page(statement, db, viewer, limit, cursor)


@router.put("/social/users/{user_id}/follow", dependencies=mutations)
def follow_user(user_id: str, db: DB, user: CurrentUser):
    lock_pair(db, user.id, user_id)
    target_user(db, user_id, user)
    if db.get(UserFollow, (user.id, user_id)) is None:
        db.add(UserFollow(follower_id=user.id, followed_id=user_id))
        notify(db, user_id, user.id, "user_follow")
    db.commit()
    return {"following": True}


@router.delete("/social/users/{user_id}/follow", status_code=204, dependencies=mutations)
def unfollow_user(user_id: str, db: DB, user: CurrentUser):
    lock_pair(db, user.id, user_id)
    db.execute(
        delete(UserFollow).where(
            UserFollow.follower_id == user.id, UserFollow.followed_id == user_id
        )
    )
    db.commit()


@router.put("/social/boards/{board_id}/follow", dependencies=mutations)
def follow_board(board_id: str, db: DB, user: CurrentUser):
    board = visible_board(db, board_id, user)
    lock_pair(db, user.id, board.owner_id)
    board = db.scalar(
        select(Board)
        .where(Board.id == board_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    # Recheck privacy after acquiring locks; publication can change concurrently.
    visible_board(db, board_id, user)
    if board.is_secret:
        raise HTTPException(404, "Board not found")
    if db.get(BoardFollow, (user.id, board_id)) is None:
        db.add(BoardFollow(follower_id=user.id, board_id=board_id))
        notify(db, board.owner_id, user.id, "board_follow", board_id)
    db.commit()
    return {"following": True}


@router.delete("/social/boards/{board_id}/follow", status_code=204, dependencies=mutations)
def unfollow_board(board_id: str, db: DB, user: CurrentUser):
    db.execute(
        delete(BoardFollow).where(
            BoardFollow.follower_id == user.id, BoardFollow.board_id == board_id
        )
    )
    db.commit()


@router.put("/social/users/{user_id}/block", dependencies=mutations)
def block_user(user_id: str, db: DB, user: CurrentUser):
    lock_pair(db, user.id, user_id)
    if db.get(UserBlock, (user.id, user_id)) is None:
        db.add(UserBlock(blocker_id=user.id, blocked_id=user_id))
    db.execute(
        delete(UserFollow).where(
            or_(
                and_(UserFollow.follower_id == user.id, UserFollow.followed_id == user_id),
                and_(UserFollow.follower_id == user_id, UserFollow.followed_id == user.id),
            )
        )
    )
    db.execute(
        delete(BoardFollow).where(
            or_(
                and_(
                    BoardFollow.follower_id == user.id,
                    BoardFollow.board_id.in_(select(Board.id).where(Board.owner_id == user_id)),
                ),
                and_(
                    BoardFollow.follower_id == user_id,
                    BoardFollow.board_id.in_(select(Board.id).where(Board.owner_id == user.id)),
                ),
            )
        )
    )
    db.execute(
        delete(Notification).where(
            or_(
                and_(Notification.recipient_id == user.id, Notification.actor_id == user_id),
                and_(Notification.recipient_id == user_id, Notification.actor_id == user.id),
            )
        )
    )
    db.commit()
    return {"blocked": True}


@router.delete("/social/users/{user_id}/block", status_code=204, dependencies=mutations)
def unblock_user(user_id: str, db: DB, user: CurrentUser):
    lock_pair(db, user.id, user_id)
    db.execute(
        delete(UserBlock).where(UserBlock.blocker_id == user.id, UserBlock.blocked_id == user_id)
    )
    db.commit()


@router.put("/social/users/{user_id}/mute", dependencies=mutations)
def mute_user(user_id: str, db: DB, user: CurrentUser):
    lock_pair(db, user.id, user_id)
    target_user(db, user_id, user)
    if db.get(UserMute, (user.id, user_id)) is None:
        db.add(UserMute(muter_id=user.id, muted_id=user_id))
    db.execute(
        delete(Notification).where(
            Notification.recipient_id == user.id, Notification.actor_id == user_id
        )
    )
    db.commit()
    return {"muted": True}


@router.delete("/social/users/{user_id}/mute", status_code=204, dependencies=mutations)
def unmute_user(user_id: str, db: DB, user: CurrentUser):
    lock_pair(db, user.id, user_id)
    db.execute(delete(UserMute).where(UserMute.muter_id == user.id, UserMute.muted_id == user_id))
    db.commit()


@router.get("/social/preferences")
def preferences(db: DB, user: CurrentUser):
    return {
        "blocked": [
            {"id": row.id, "display_name": row.display_name}
            for row in db.scalars(
                select(User)
                .join(UserBlock, UserBlock.blocked_id == User.id)
                .where(UserBlock.blocker_id == user.id)
                .order_by(User.id)
                .limit(100)
            )
        ],
        "muted": [
            {"id": row.id, "display_name": row.display_name}
            for row in db.scalars(
                select(User)
                .join(UserMute, UserMute.muted_id == User.id)
                .where(UserMute.muter_id == user.id)
                .order_by(User.id)
                .limit(100)
            )
        ],
    }


@router.get("/notifications")
def notifications(
    db: DB,
    user: CurrentUser,
    limit: PageLimit = 30,
    cursor: Annotated[str | None, Query(max_length=300)] = None,
):
    statement = select(Notification, User.display_name).join(User, User.id == Notification.actor_id)
    statement = statement.where(
        Notification.recipient_id == user.id,
        visible_owner(Notification.actor_id, user, include_muted=True),
    )
    position = cursor_value(cursor)
    if position:
        timestamp, notification_id = position
        statement = statement.where(
            or_(
                Notification.created_at < timestamp,
                and_(Notification.created_at == timestamp, Notification.id < notification_id),
            )
        )
    rows = db.execute(
        statement.order_by(Notification.created_at.desc(), Notification.id.desc()).limit(limit + 1)
    ).all()
    return {
        "items": [
            {
                "id": row.id,
                "actor_id": row.actor_id,
                "actor_name": name,
                "kind": row.kind,
                "board_id": row.board_id,
                "created_at": row.created_at,
                "read_at": row.read_at,
            }
            for row, name in rows[:limit]
        ],
        "next_cursor": base64.urlsafe_b64encode(
            json.dumps(
                [
                    rows[limit - 1][0].created_at.isoformat(),
                    rows[limit - 1][0].id,
                ]
            ).encode()
        ).decode()
        if len(rows) > limit
        else None,
    }


@router.put("/notifications/{notification_id}/read", status_code=204, dependencies=mutations)
def read_notification(notification_id: str, db: DB, user: CurrentUser):
    row = db.scalar(
        select(Notification)
        .where(Notification.id == notification_id, Notification.recipient_id == user.id)
        .with_for_update()
    )
    if row is None:
        raise HTTPException(404, "Notification not found")
    row.read_at = row.read_at or utcnow()
    db.commit()
