# StudyLens

An in-flow research-paper reading assistant. Read a PDF in the browser,
highlight the sentence that lost you, pick an explanation lens, and the
explanation streams in next to the passage — no chat box, no tab-switching.


## How it works

1. Add a paper by URL or arXiv ID. The backend fetches the PDF, extracts text
   per-page with PyMuPDF, and stores it.
2. Open it in the in-browser reader (raw `pdfjs-dist`, no wrapper library).
3. Select any passage — a small picker appears with all nine lenses.
4. Pick one; the explanation streams in via SSE into a gutter card next to
   the passage, which stays highlighted while the card is open.
5. Selecting new text collapses the current card to a tint on its passage;
   clicking a tint reopens its saved explanation with no re-fetch.

No RAG, no whole-paper context — each explanation is scoped to the selected
passage plus its page, deliberately, to keep latency low and answers
grounded in what the reader is actually looking at.

## Stack

**Backend** — Python, FastAPI + Uvicorn, SQLAlchemy 2.0 over Postgres
(`psycopg`), Alembic migrations, Pydantic/pydantic-settings, PyMuPDF for PDF
extraction, `httpx` for outbound calls. The LLM client
(`backend/app/services/llm/`) speaks raw OpenAI-compatible HTTP — no vendor
SDK — so swapping providers is a config change, not a code change.

**Frontend** — TypeScript, React 18, Vite, Tailwind CSS v4, `pdfjs-dist` used
directly. No router, no client-data-fetching library — the app is two views
and a handful of endpoints, so plain `fetch` + React state is enough.

**Data** — Postgres 15, run via Docker Compose. 

**LLM** — provider-agnostic via one OpenAI-compatible client; currently
pointed at Groq (`llama-3.3-70b-versatile`) for its combination of writing
quality and LPU-grade streaming speed.

## Running it

```
cp .env.example .env
# fill in LLM_API_KEY and LLM_MODEL — see comments in .env.example for
# provider options (Groq, Cerebras, OpenRouter, Ollama, OpenAI)

docker compose up -d
```

- API: http://localhost:8000 (`/health` checks Postgres connectivity)
- Frontend: http://localhost:5173
- Backend code is bind-mounted with `uvicorn --reload`; frontend runs the
  Vite dev server the same way. Edits on the host take effect immediately.

After editing `.env`, restart with `docker compose up -d --force-recreate api`
— a plain `restart` does not reload environment variables.

