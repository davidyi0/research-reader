# In-Flow Paper Reading Assistant — Design

## What this is

A reader for research papers that explains things where you're already looking.

You open a paper, hit a sentence that loses you, highlight it, and pick how you want it explained — simplify, give me an analogy, walk me through the equation, what's the assumption here. The explanation appears in place. You never leave the paper, never write a prompt, never re-establish context in a chat window.

**It is not a chat interface over PDFs.** That product already exists — you can paste a PDF into any chat model. The differentiator here is the interaction, not the model.

## Constraints that drive the design

1. **Latency is the product.** A 15-second response breaks reading flow badly enough that you'd go back to a chat tab. Every decision below optimizes time-to-first-token over capability.
2. **The LLM is a swappable dependency.** One provider interface, developed against a free OpenAI-compatible endpoint. Nothing vendor-specific on the critical path.
3. **Local-first, deploy-ready.** Runs on localhost for now. The few decisions that are expensive to retrofit are made up front; the rest of deployment is deferred.

## History

This repo started as StudyLens — course-material Q&A over uploaded PDFs, a conventional RAG project. It was retired at Phase 1 / Milestone 1 with infra and schema built but zero retrieval code written, and repurposed into this. The infrastructure (compose, Alembic, config, database session handling) carried over; the product did not.

---

## Delivery form

**A standalone web app**, served locally via the compose stack at `localhost:5173`.

Alternatives considered:

| | Verdict |
|---|---|
| **Browser extension** | Chrome's built-in PDF viewer is a closed plugin — content scripts can't reach its text layer or read selections from it. The workaround is redirecting PDF URLs to your own bundled pdf.js, which means shipping the viewer *and* the extension plumbing: both costs, neither benefit. Only wins for readers who use arXiv HTML versions exclusively. |
| **Desktop app (Tauri)** | Removes the import step, but the viewer still has to be built, plus packaging and a Rust toolchain. No tablet access. |
| **Zotero 7 plugin** | Best leverage-to-effort *if* Zotero is the library — its reader and text layer already exist. Not applicable: papers here live in browser tabs, not a reference manager. |

### The reading workflow this targets

Papers arrive as links — arXiv, OpenReview, ACL — get read in a tab, and get lost.

- **URL ingest is primary; file upload is the fallback.** Paste `arxiv.org/abs/2401.12345` and the backend fetches the PDF. Accepts arXiv ID or URL, DOI, direct PDF link, or multipart upload for anything paywalled.
- **arXiv metadata comes from the arXiv API** (`export.arxiv.org/api/query`) — title, authors, abstract, date. No LLM call needed for the dominant case. DOIs resolve via Crossref, with OpenAlex/Unpaywall for an open-access PDF link.
- **The paper list is a real feature.** It becomes the library that doesn't otherwise exist. Sorted by last-read, showing reading position.

Publishers behind Cloudflare or paywalls will block automated fetching. Fail gracefully to "upload it yourself."

### Decisions made now to avoid retrofitting

- All file access behind `StorageService` — local filesystem now, S3 as a one-class swap.
- Every setting via env in `app/core/config.py`. No hardcoded paths, hosts, or origins.
- LLM keys stay server-side; the frontend never calls a model directly.
- `user_id` on every row from day one, even while a single seeded user is hardcoded — auth then becomes a dependency swap, not a migration.
- No local-filesystem assumptions in the frontend; PDFs are served via `GET /papers/{id}/file`.

Deferred deliberately: auth, S3, frontend Dockerfile and static build, rate limiting, SSRF validation on URL fetching, CI. **Deploy is decoupled from the feature phases** and can slot in any time after P2.

---

## Provider strategy

### Interface

`app/services/llm/` exposes two operations:

```python
class LLMProvider(Protocol):
    async def stream(self, *, system: str, user: str) -> AsyncIterator[str]: ...
    async def structured(self, *, system: str, user: str, schema: dict) -> dict: ...
```

A single `OpenAICompatProvider` covers Groq, Cerebras, OpenRouter, Ollama, Google's OpenAI-compatible endpoint, and OpenAI itself — they differ only by `LLM_BASE_URL` / `LLM_API_KEY` / `LLM_MODEL`. Switching is an env change. Nothing above this layer knows which model is running.

**Dev default: Groq free tier** — OpenAI-compatible, and the fastest inference generally available, which is the property this product needs. Cerebras is equivalent; Ollama covers offline work at the cost of local hardware.

### What going generic costs

| Vendor-specific feature | Replacement |
|---|---|
| Native PDF document blocks | PyMuPDF text extraction at ingest. Store per-page text; send text, not PDFs. |
| Explicit prompt caching | Scoped context (below). Keep prompt prefixes byte-stable anyway — several providers do automatic prefix caching with no API surface. |
| Grounded citations with page numbers | Deterministic search over extracted text. For "where was this first defined," find the first occurrence and hand the model that passage — more reliable than a model self-reporting a page. |
| A real token counter | `len(text) // 4` as a budget guard. **Not `tiktoken`** — it's OpenAI's tokenizer and materially wrong for Llama/Qwen/Gemini-class models. |

### Scoped context

Whole-paper-in-context (~25k tokens) is only economical with explicit prompt caching. Without it that's 25k tokens *per selection*, which exhausts free-tier tokens-per-minute limits almost immediately.

Context is assembled locally instead. Each request carries:

1. Title + abstract (~200 tokens) — anchors the domain
2. All section headings (~100 tokens) — cheap global map
3. The current section, or a window around the selection if the section is long (~1–2k tokens)
4. The selected text, marked explicitly
5. Terms already explained this session (~100 tokens)

Total ≈ 2–3k tokens — fast, cheap, inside free-tier limits, and faster than the whole-paper approach.

**The loss:** cross-page reference resolution. "The aforementioned regularizer" defined six pages earlier falls outside the window. Mitigations: the abstract + heading map resolves most cross-references in practice; and the model is instructed to emit a bare `NEED_MORE_CONTEXT` sentinel when it can't resolve something, triggering one retry with a widened window. That pays a round trip on the minority of cases rather than full context on all of them.

`LLM_MAX_CONTEXT_TOKENS` is configurable, so widening to whole-paper against a frontier model is a config change.

### Quality expectation

Free-tier open-weight models are meaningfully weaker at explaining dense technical prose than frontier models. Expect Simplify and Analogy to land reasonably and Assumption unpacking to be shakier. That's the correct trade for development, and the provider interface is what makes it recoverable. A manual comparison harness (~10 fixed selections from a well-understood paper) runs from P2 onward, and `explanations.model` records which model produced each result.

---

## Features

**Core**
1. Select-to-explain — highlight → explanation in place
2. Lens menu on the selection:
   - Simplify · Analogy · Concrete example · Why it matters · Contrast · Assumption unpacking · Step decomposition · Restate as a question
   - **Equation breakdown** — term-by-term walkthrough of a formula's symbols. Distinct from Step decomposition, which handles procedural prose.
   - **Depth dial** — "simpler" / "deeper" on the result card. The escape hatch when a lens misses, and why no chat box is needed. Threads via `explanations.parent_id`.
   - **Figure/region explanation** — select a figure, caption, or table. Papers are ~40% figures. Requires a vision-capable model; gated behind a provider capability flag.

**Supporting**
3. Jargon/symbol resolution — definition from where the term was first defined, page-linked via deterministic first-occurrence search
4. Prerequisite surfacing — flag assumed background, offer an inline primer
5. Running glossary/notation panel — passive sidebar, auto-populates
6. Persistent paper memory — don't re-explain what's covered; re-surface via the glossary

**Later**
7. Section-level TL;DRs on demand
8. Personalization / explain-to-my-level
9. Reading position memory

**v2+**
10. Contribution map · 11. Claim-to-evidence linking · 12. Dependency backlinks · 13. Cross-paper comparison

> Lens usage is instrumented from day one. Some lenses will collapse in practice — Analogy vs. Concrete example, Why it matters vs. Restate as a question. Build all nine, log which get picked, prune at P5. Nine items is already at the edge of a usable popover.

---

## Riskiest engineering: PDF text selection

Everything depends on turning a browser selection over a rendered PDF into something the model can act on. `pdfjs-dist` renders a text layer of positioned spans over a canvas; `window.getSelection()` works over it, but selections spanning page or column boundaries map messily.

**Character-exact offsets aren't needed.** The requirement is `{page_number, selected_text}`. Context assembly locates that string in the PyMuPDF-extracted page text — a plain string search, not coordinate math. Precise anchoring only matters for *persisting* highlights across sessions, a later concern.

Rejected: rendering extracted text instead of the PDF. Selection becomes trivial, but equation and figure rendering is lost — fatal for a paper reader.

**P1 is a spike on exactly this.** If selection mapping doesn't work, the product doesn't exist.

---

## Schema

Every table carries `user_id` or an FK chain to it.

**`users`** — `id` · `email` · `password_hash` · `created_at`

**`papers`** — `id` · `user_id` → users CASCADE · `source_url` · `arxiv_id` · `doi` · `title` · `authors` JSONB · `year` · `venue` · `abstract` · `storage_key` · `page_count` · `last_page` · `status` (`pending → processing → ready | failed`) · `created_at` · `last_read_at`

**`pages`** — `id` · `paper_id` → papers CASCADE · `page_number` · `text` · unique(`paper_id`, `page_number`)
PyMuPDF extraction output. Backs context assembly, first-occurrence search, and figure region lookup. **This table is why the design needs no vector store.**

**`sections`** — `id` · `paper_id` CASCADE · `parent_id` self-FK · `label` (`"3.2"`) · `title` · `level` · `page_start` · `page_end` · `order_index`

**`explanations`** — `id` · `paper_id` CASCADE · `parent_id` self-FK (depth-dial threads) · `lens` · `selected_text` · `page_number` · `response` · `model` · `created_at`

**`terms`** — `id` · `paper_id` CASCADE · `term` · `definition` · `first_seen_page` · `source_explanation_id` · `created_at` · unique(`paper_id`, `term`)

Paper memory is a query, not a table: `SELECT term FROM terms WHERE paper_id = ?`, injected into the prompt suffix.

**No `chunks` table.** It arrives with cross-paper comparison, where retrieval finally becomes load-bearing.

---

## Phases

| | Scope |
|---|---|
| **P0** | Reset: this doc, config/schema rewrite, provider interface |
| **P1** | Ingest (URL-first) + selection spike + one lens. **Measure TTFT — release gate.** |
| **P2** | Full lens menu, depth dial, figure explanation. **Honest go/no-go gate.** |
| **P3** | Section structure, jargon resolution, prerequisite surfacing |
| **P4** | Glossary panel + paper memory |
| **P5** | TL;DRs, personalization, reading position, lens prune |
| **P6** | Contribution map, claim-to-evidence, dependency backlinks |
| **P7** | Deploy: auth, S3, static build, rate limiting, SSRF validation, tests, CI |
| **P8** | Cross-paper comparison — where retrieval finally enters |

**The gate at P2 is real:** if reading a paper in the app doesn't beat highlighting text and pasting it into a chat model, stop and reconsider before building P3.
