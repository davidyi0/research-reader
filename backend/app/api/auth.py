"""Google Sign-In endpoint. Exchanges a verified Google ID token for our own
session JWT and upserts the User row on first sign-in.
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.models import User
from app.services.auth import AuthError, issue_session_token, verify_google_token

router = APIRouter(prefix="/auth", tags=["auth"])


class GoogleSignInIn(BaseModel):
    credential: str  # the ID token from Google's Sign-In button


class SessionOut(BaseModel):
    token: str
    email: str
    name: str | None


@router.post("/google", response_model=SessionOut)
def google_sign_in(body: GoogleSignInIn) -> SessionOut:
    try:
        email, name = verify_google_token(body.credential)
    except AuthError as exc:
        raise HTTPException(401, str(exc)) from exc

    db: Session = SessionLocal()
    try:
        user = db.query(User).filter_by(email=email).first()
        if user is None:
            user = User(email=email, name=name)
            db.add(user)
            db.commit()
            db.refresh(user)
        elif name and user.name != name:
            user.name = name
            db.commit()

        token = issue_session_token(user.id)
        return SessionOut(token=token, email=user.email, name=user.name)
    finally:
        db.close()
