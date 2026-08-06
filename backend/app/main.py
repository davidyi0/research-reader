"""API entrypoint.

Exposes `/health`, which verifies the API can actually reach Postgres, not just
that the process is alive, plus the P1 papers router (ingest, library, explain).
"""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.api.papers import router as papers_router
from app.core.config import settings
from app.core.database import engine
from app.services.llm import close_provider

logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # The provider holds one long-lived httpx client (a fresh connection per
    # request would add a TLS handshake to time-to-first-token). Release it on
    # shutdown. Construction stays lazy, so importing this costs nothing.
    yield
    await close_provider()


app = FastAPI(title="Paper Reader API", version="0.1.0", lifespan=lifespan)

# Allow the Vite dev server to call the API from the browser.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.FRONTEND_ORIGIN],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(papers_router)


def _check_postgres() -> bool:
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


@app.get("/health")
def health() -> dict:
    """Readiness check: reports per-dependency status so a red light is diagnosable."""
    checks = {"postgres": _check_postgres()}
    status = "ok" if all(checks.values()) else "degraded"
    return {"status": status, "checks": checks}
