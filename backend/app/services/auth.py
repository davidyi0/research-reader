"""Google Sign-In verification + our own session JWT.

Two separate tokens on purpose: the Google ID token only proves identity at
sign-in time and we don't want to re-verify against Google on every request,
so we mint a short-lived-ish JWT of our own (`JWT_EXPIRES_DAYS`) that the
frontend attaches as a Bearer token from then on.
"""
import time
import uuid

import jwt
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token

from app.core.config import settings

_google_request = google_requests.Request()


class AuthError(Exception):
    pass


def verify_google_token(credential: str) -> tuple[str, str | None]:
    """Returns (email, name) for a valid Google ID token, or raises AuthError."""
    try:
        claims = id_token.verify_oauth2_token(
            credential, _google_request, settings.GOOGLE_CLIENT_ID
        )
    except ValueError as exc:
        raise AuthError(f"Invalid Google token: {exc}") from exc

    if not claims.get("email_verified", False):
        raise AuthError("Google account email is not verified")

    email = claims["email"]
    if settings.ALLOWED_EMAILS:
        allowed = {e.strip().lower() for e in settings.ALLOWED_EMAILS.split(",") if e.strip()}
        if email.lower() not in allowed:
            raise AuthError("This email is not on the allowlist")

    return email, claims.get("name")


def issue_session_token(user_id: uuid.UUID) -> str:
    payload = {
        "sub": str(user_id),
        "exp": int(time.time()) + settings.JWT_EXPIRES_DAYS * 86400,
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm="HS256")


def decode_session_token(token: str) -> uuid.UUID:
    try:
        payload = jwt.decode(token, settings.JWT_SECRET, algorithms=["HS256"])
        return uuid.UUID(payload["sub"])
    except (jwt.PyJWTError, ValueError, KeyError) as exc:
        raise AuthError(f"Invalid session token: {exc}") from exc
