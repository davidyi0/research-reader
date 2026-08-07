"""Seed one dev user, kept around for local testing without a real Google sign-in.

Real users are created on first Google sign-in (see app/api/auth.py); this is
just a convenience row so scripts/manual API testing has a stable user to
attach papers to.

Idempotent: re-running is a no-op once the dev user is present. Run with:
    docker compose exec api python -m scripts.seed
"""
from app.core.database import SessionLocal
from app.models import User

DEV_EMAIL = "dev@localhost"


def seed() -> None:
    db = SessionLocal()
    try:
        existing = db.query(User).filter_by(email=DEV_EMAIL).first()
        if existing:
            print(f"Dev user {DEV_EMAIL} already exists ({existing.id}) — nothing to do.")
            return

        user = User(email=DEV_EMAIL, name="Dev User")
        db.add(user)
        db.commit()
        print(f"Seeded dev user {user.id} ({DEV_EMAIL}).")
    finally:
        db.close()


if __name__ == "__main__":
    seed()
