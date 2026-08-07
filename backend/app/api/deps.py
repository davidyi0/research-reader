"""Shared request dependencies."""
from fastapi import Depends, Header, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models import User
from app.services.auth import AuthError, decode_session_token


def current_user(
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> User:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Missing or malformed Authorization header")
    token = authorization.removeprefix("Bearer ").strip()
    try:
        user_id = decode_session_token(token)
    except AuthError as exc:
        raise HTTPException(401, str(exc)) from exc

    user = db.query(User).filter_by(id=user_id).first()
    if user is None:
        raise HTTPException(401, "User no longer exists")
    return user
