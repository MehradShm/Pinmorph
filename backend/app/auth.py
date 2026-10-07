import hashlib
import secrets
from datetime import timedelta
from typing import Annotated

from argon2 import PasswordHasher
from argon2.exceptions import VerificationError
from fastapi import Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session

from app.models import AuthSession, User, utcnow

COOKIE_NAME = "pinmorph_session"
password_hasher = PasswordHasher()
# A missing account still performs a hash check to avoid a quick account-existence signal.
dummy_hash = password_hasher.hash(secrets.token_urlsafe(32))


def get_db(request: Request):
    with Session(request.app.state.engine) as session:
        yield session


DB = Annotated[Session, Depends(get_db)]


def check_origin(request: Request):
    # SameSite cookies plus an Origin check protect browser mutations. API clients omit Origin.
    origin = request.headers.get("origin")
    if origin and origin not in request.app.state.settings.trusted_origins:
        raise HTTPException(403, "Untrusted request origin")


def token_digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def optional_user(request: Request, db: DB) -> User | None:
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        return None
    auth_session = db.get(AuthSession, token_digest(token))
    if not auth_session or auth_session.expires_at <= utcnow():
        return None
    return db.get(User, auth_session.user_id)


def current_user(user: Annotated[User | None, Depends(optional_user)]) -> User:
    if user is None:
        raise HTTPException(401, "Please sign in")
    return user


CurrentUser = Annotated[User, Depends(current_user)]
OptionalUser = Annotated[User | None, Depends(optional_user)]


def start_session(request: Request, response: Response, db: Session, user: User):
    settings = request.app.state.settings
    old_token = request.cookies.get(COOKIE_NAME)
    if old_token:
        old_session = db.get(AuthSession, token_digest(old_token))
        if old_session:
            db.delete(old_session)
    token = secrets.token_urlsafe(32)
    db.add(
        AuthSession(
            token_hash=token_digest(token),
            user_id=user.id,
            expires_at=utcnow() + timedelta(days=settings.session_days),
        )
    )
    db.commit()
    response.set_cookie(
        COOKIE_NAME,
        token,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        max_age=settings.session_days * 86400,
        path="/api",
    )
    response.headers["Cache-Control"] = "no-store"


def verify_password(encoded: str | None, password: str) -> bool:
    try:
        return password_hasher.verify(encoded or dummy_hash, password) and encoded is not None
    except VerificationError:
        return False
