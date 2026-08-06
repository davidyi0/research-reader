"""Paper ingest, listing, file serving, and the explanation stream."""
import json
import logging
import time
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import SessionLocal, get_db
from app.models import Explanation, Page, Paper, User
from app.services import context, fetch
from app.services.extract import extract
from app.services.lenses import LENSES
from app.services.llm import LLMError, get_provider
from app.services.storage import storage

router = APIRouter(prefix="/papers", tags=["papers"])
logger = logging.getLogger(__name__)

DEV_EMAIL = "dev@localhost"


def current_user(db: Session = Depends(get_db)) -> User:
    """The seeded dev user. Swapped for real auth at P7 — no schema change."""
    user = db.query(User).filter_by(email=DEV_EMAIL).first()
    if user is None:
        raise HTTPException(500, "Dev user missing — run `python -m scripts.seed`.")
    return user


class PaperOut(BaseModel):
    id: uuid.UUID
    title: str | None
    authors: list | None
    year: int | None
    venue: str | None
    status: str
    page_count: int | None
    last_page: int | None
    source_url: str | None
    error: str | None = None

    model_config = {"from_attributes": True}


class ExplainIn(BaseModel):
    # Character-exact offsets are deliberately not required; a page number and
    # the selected string are enough to locate the passage server-side.
    page_number: int
    selected_text: str
    lens: str = "simplify"


class LensOut(BaseModel):
    key: str
    label: str


@router.get("/lenses")
def list_lenses() -> list[LensOut]:
    return [LensOut(key=lens.key, label=lens.label) for lens in LENSES.values()]


def _ingest(paper_id: uuid.UUID, pdf_bytes: bytes) -> None:
    """Extract page text in the background so the reader can open immediately."""
    db = SessionLocal()
    try:
        paper = db.get(Paper, paper_id)
        if paper is None:
            return
        # `commit()` is inside this try too: a row that fails to *persist* (seen
        # with a real paper whose embedded font decoded to a NUL byte, which
        # Postgres text columns reject) must still end up `failed`, not stuck at
        # `processing` forever.
        try:
            result = extract(pdf_bytes)
            if result.is_scanned:
                # Renders perfectly, selects nothing. Has to be said out loud or
                # it looks like the app is broken.
                paper.status = "failed"
                paper.error = "This PDF is a scan with no text layer, so passages can't be selected."
            else:
                db.add_all([
                    Page(paper_id=paper.id, page_number=i, text=text)
                    for i, text in enumerate(result.pages, start=1)
                ])
                paper.page_count = result.page_count
                paper.status = "ready"
            db.commit()
        except Exception as exc:  # noqa: BLE001 - surface any extraction/persist failure
            db.rollback()
            paper.status = "failed"
            paper.error = f"Could not read this PDF: {exc}"
            db.commit()
    finally:
        db.close()


@router.post("", response_model=PaperOut, status_code=201)
def create_paper(
    background: BackgroundTasks,
    source: str | None = Form(None),
    file: UploadFile | None = File(None),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> Paper:
    """Ingest by arXiv ID/URL, DOI, or PDF URL (`source`), or by upload (`file`)."""
    if not source and file is None:
        raise HTTPException(400, "Provide either a `source` URL/ID or a `file` upload.")

    try:
        result = (
            fetch.from_upload(file.filename, file.file.read())
            if file is not None
            else fetch.fetch(source)
        )
    except fetch.FetchError as exc:
        raise HTTPException(422, str(exc)) from exc

    paper = Paper(
        user_id=user.id,
        source_url=result.source_url,
        arxiv_id=result.arxiv_id,
        doi=result.doi,
        title=result.title,
        authors=result.authors or None,
        year=result.year,
        venue=result.venue,
        abstract=result.abstract,
        storage_key="",  # replaced below, once the row has an id to key on
        status="processing",
    )
    db.add(paper)
    db.flush()
    paper.storage_key = storage.write(paper.id, result.filename, result.pdf_bytes)
    db.commit()
    db.refresh(paper)

    background.add_task(_ingest, paper.id, result.pdf_bytes)
    return paper


@router.get("", response_model=list[PaperOut])
def list_papers(
    db: Session = Depends(get_db), user: User = Depends(current_user)
) -> list[Paper]:
    """The library: most recently read first, then most recently added."""
    return (
        db.query(Paper)
        .filter_by(user_id=user.id)
        .order_by(Paper.last_read_at.desc().nullslast(), Paper.created_at.desc())
        .all()
    )


def _get_paper(db: Session, user: User, paper_id: uuid.UUID) -> Paper:
    paper = db.query(Paper).filter_by(id=paper_id, user_id=user.id).first()
    if paper is None:
        raise HTTPException(404, "No such paper.")
    return paper


@router.get("/{paper_id}/file")
def get_file(
    paper_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> FileResponse:
    """Serve the PDF. The frontend never touches the filesystem itself."""
    paper = _get_paper(db, user, paper_id)
    paper.last_read_at = datetime.now(timezone.utc)
    db.commit()
    return FileResponse(storage.path(paper.storage_key), media_type="application/pdf")


@router.post("/{paper_id}/explain")
def explain(
    paper_id: uuid.UUID,
    body: ExplainIn,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> StreamingResponse:
    """Stream one Simplify explanation as SSE.

    Note the session handling. `app.core.database` is a *sync* engine, and
    holding a sync Session open across an await-heavy stream would block the
    event loop. So every read happens here, before the stream opens; the
    generator below holds no session; and the row is written afterwards from a
    fresh short-lived one.
    """
    lens = LENSES.get(body.lens)
    if lens is None:
        raise HTTPException(422, f"Unknown lens: {body.lens!r}")

    paper = _get_paper(db, user, paper_id)
    page = (
        db.query(Page)
        .filter_by(paper_id=paper.id, page_number=body.page_number)
        .first()
    )
    if page is None:
        raise HTTPException(
            409, "That page has no extracted text yet — the paper may still be processing."
        )

    user_message = context.build(
        paper, page.text, body.selected_text, settings.LLM_MAX_CONTEXT_TOKENS
    )
    paper_id_, page_number, selected_text = paper.id, body.page_number, body.selected_text

    async def event_stream():
        provider = get_provider()
        parts: list[str] = []
        t0 = time.perf_counter()
        first_delta = True
        try:
            async for delta in provider.stream(system=lens.system, user=user_message):
                if first_delta:
                    logger.info("explain TTFT=%.3fs paper=%s page=%s", time.perf_counter() - t0, paper_id_, page_number)
                    first_delta = False
                parts.append(delta)
                yield f"data: {json.dumps({'delta': delta})}\n\n"
        except LLMError as exc:
            yield f"data: {json.dumps({'error': str(exc)})}\n\n"
            return

        response = "".join(parts)
        if response:
            write_db = SessionLocal()
            try:
                write_db.add(
                    Explanation(
                        paper_id=paper_id_,
                        lens=lens.key,
                        selected_text=selected_text,
                        page_number=page_number,
                        response=response,
                        model=provider.model,
                    )
                )
                write_db.commit()
            finally:
                write_db.close()
        yield f"data: {json.dumps({'done': True})}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        # Without this an intermediary can buffer the stream and destroy TTFT.
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
