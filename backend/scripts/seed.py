"""Seed one dev user so papers have a valid owner before auth exists.

Every table carries a user FK from day one, so ingest needs a user id even
though there is no login yet. Adding auth later swaps the hardcoded lookup for
a `get_current_user` dependency — no migration.

Idempotent: re-running is a no-op once the dev user is present. Run with:
    docker compose exec api python -m scripts.seed
"""
from app.core.database import SessionLocal
from app.models import User

DEV_EMAIL = "dev@localhost"
# Placeholder until the deploy phase replaces this with a real bcrypt hash.
DEV_PASSWORD_HASH = "placeholder-not-a-real-hash"


def seed() -> None:
    db = SessionLocal()
    try:
        existing = db.query(User).filter_by(email=DEV_EMAIL).first()
        if existing:
            print(f"Dev user {DEV_EMAIL} already exists ({existing.id}) — nothing to do.")
            return

        user = User(email=DEV_EMAIL, password_hash=DEV_PASSWORD_HASH)
        db.add(user)
        db.commit()
        print(f"Seeded dev user {user.id} ({DEV_EMAIL}).")
    finally:
        db.close()


if __name__ == "__main__":
    seed()
