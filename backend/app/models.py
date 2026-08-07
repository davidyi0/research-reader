"""SQLAlchemy ORM models.

All in one module while the schema is small and tightly related; split into a
`models/` package later only if it grows. SQLAlchemy 2.0 typed style
(`Mapped` / `mapped_column`). Mirrors the schema in docs/DESIGN.md.

Note on `pages`: it holds the PyMuPDF text extraction, and it is what lets the
whole design work without a vector store — context assembly, first-occurrence
term lookup, and figure region lookup all read from it.
"""
import uuid
from datetime import datetime

from sqlalchemy import (
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

_uuid_pk = lambda: mapped_column(
    UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
)


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = _uuid_pk()
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    # From the Google ID token at first sign-in. Auth is Google-only — no
    # password to store.
    name: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    papers: Mapped[list["Paper"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class Paper(Base):
    __tablename__ = "papers"
    # The library list is "my papers, most recently read first" — index for it.
    __table_args__ = (Index("ix_papers_user_last_read", "user_id", "last_read_at"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    # Present from day one even though a single seeded user is hardcoded, so
    # adding auth later is a dependency swap rather than a migration.
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )

    # Provenance. URL ingest is the primary path; all three are null for uploads.
    source_url: Mapped[str | None] = mapped_column(Text)
    arxiv_id: Mapped[str | None] = mapped_column(String(64))
    doi: Mapped[str | None] = mapped_column(String(255))

    # Metadata: from the arXiv/Crossref API where available, otherwise from a
    # structured LLM call at ingest.
    title: Mapped[str | None] = mapped_column(Text)
    authors: Mapped[list | None] = mapped_column(JSONB)
    year: Mapped[int | None] = mapped_column(Integer)
    venue: Mapped[str | None] = mapped_column(Text)
    abstract: Mapped[str | None] = mapped_column(Text)

    storage_key: Mapped[str] = mapped_column(Text, nullable=False)
    page_count: Mapped[int | None] = mapped_column(Integer)

    # Reading position — the library shows it, reopening restores it.
    last_page: Mapped[int | None] = mapped_column(Integer)
    last_read_at: Mapped[datetime | None] = mapped_column()

    # Lifecycle: pending -> processing -> ready | failed
    status: Mapped[str] = mapped_column(String(50), server_default="pending")
    # Set when status = failed (fetch/extract error, or a scanned PDF with no
    # text layer). A silent failure here looks like a broken app, since the PDF
    # still renders fine even when selection has nothing to work with.
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    user: Mapped["User"] = relationship(back_populates="papers")
    pages: Mapped[list["Page"]] = relationship(
        back_populates="paper", cascade="all, delete-orphan"
    )
    sections: Mapped[list["Section"]] = relationship(
        back_populates="paper", cascade="all, delete-orphan"
    )
    explanations: Mapped[list["Explanation"]] = relationship(
        back_populates="paper", cascade="all, delete-orphan"
    )
    terms: Mapped[list["Term"]] = relationship(
        back_populates="paper", cascade="all, delete-orphan"
    )


class Page(Base):
    """One row per PDF page, holding extracted text.

    Context assembly locates a user's selected string in here to find the
    surrounding section — a plain string search, not coordinate math.
    """

    __tablename__ = "pages"
    __table_args__ = (UniqueConstraint("paper_id", "page_number", name="uq_pages_paper_page"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    paper_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("papers.id", ondelete="CASCADE"), nullable=False
    )
    page_number: Mapped[int] = mapped_column(Integer, nullable=False)  # 1-indexed
    text: Mapped[str] = mapped_column(Text, nullable=False)

    paper: Mapped["Paper"] = relationship(back_populates="pages")


class Section(Base):
    """The paper's section tree, used to scope context around a selection."""

    __tablename__ = "sections"
    __table_args__ = (Index("ix_sections_paper_order", "paper_id", "order_index"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    paper_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("papers.id", ondelete="CASCADE"), nullable=False
    )
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("sections.id", ondelete="CASCADE")
    )
    label: Mapped[str | None] = mapped_column(String(32))  # e.g. "3.2"
    title: Mapped[str] = mapped_column(Text, nullable=False)
    level: Mapped[int] = mapped_column(Integer, server_default="1")
    page_start: Mapped[int | None] = mapped_column(Integer)
    page_end: Mapped[int | None] = mapped_column(Integer)
    order_index: Mapped[int] = mapped_column(Integer, nullable=False)

    paper: Mapped["Paper"] = relationship(back_populates="sections")
    parent: Mapped["Section | None"] = relationship(
        back_populates="children", remote_side="Section.id"
    )
    children: Mapped[list["Section"]] = relationship(
        back_populates="parent", cascade="all, delete-orphan"
    )


class Explanation(Base):
    """One lens invocation on one selection.

    `parent_id` threads depth-dial follow-ups ("simpler" / "deeper") under the
    original, which is what removes the need for a free-form chat box.
    """

    __tablename__ = "explanations"
    __table_args__ = (Index("ix_explanations_paper_created", "paper_id", "created_at"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    paper_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("papers.id", ondelete="CASCADE"), nullable=False
    )
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("explanations.id", ondelete="CASCADE")
    )

    lens: Mapped[str] = mapped_column(String(32), nullable=False)
    selected_text: Mapped[str] = mapped_column(Text, nullable=False)
    page_number: Mapped[int] = mapped_column(Integer, nullable=False)
    response: Mapped[str] = mapped_column(Text, nullable=False)
    # Which model produced this — the free-tier vs frontier comparison harness
    # needs it, and it makes regressions attributable after a provider swap.
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    paper: Mapped["Paper"] = relationship(back_populates="explanations")
    parent: Mapped["Explanation | None"] = relationship(
        back_populates="children", remote_side="Explanation.id"
    )
    children: Mapped[list["Explanation"]] = relationship(
        back_populates="parent", cascade="all, delete-orphan"
    )


class Term(Base):
    """Glossary entry, extracted from explanations off the critical path.

    Doubles as paper memory: the set of terms already covered is queried from
    here and injected into the prompt so the model stops re-explaining them.
    """

    __tablename__ = "terms"
    __table_args__ = (UniqueConstraint("paper_id", "term", name="uq_terms_paper_term"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    paper_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("papers.id", ondelete="CASCADE"), nullable=False
    )
    term: Mapped[str] = mapped_column(String(255), nullable=False)
    definition: Mapped[str] = mapped_column(Text, nullable=False)
    # Found by deterministic search over `pages`, not by asking the model —
    # a model self-reporting a page number is not trustworthy.
    first_seen_page: Mapped[int | None] = mapped_column(Integer)
    source_explanation_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("explanations.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    paper: Mapped["Paper"] = relationship(back_populates="terms")
