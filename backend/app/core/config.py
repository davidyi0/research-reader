"""Centralized application settings.

Every environment-dependent value flows through this one `Settings` object so the
rest of the app never reads `os.environ` directly. Pydantic validates types and
raises on startup if a required value is missing — fail loud, fail early.
"""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Connection string (default matches the `postgres` service in compose).
    DATABASE_URL: str = "postgresql+psycopg://studylens:studylens@postgres:5432/studylens"

    # --- LLM provider -------------------------------------------------------
    # Any OpenAI-compatible endpoint: Groq, Cerebras, OpenRouter, Ollama,
    # Google's compat endpoint, OpenAI. Switching providers is a change to
    # these three values and nothing else — see app/services/llm/.
    LLM_BASE_URL: str = "https://api.groq.com/openai/v1"
    LLM_API_KEY: str = ""
    LLM_MODEL: str = ""
    # Budget guard for assembled context. Deliberately approximate — see
    # `estimate_tokens` in app/services/llm/base.py for why there's no tokenizer.
    LLM_MAX_CONTEXT_TOKENS: int = 3000
    LLM_TIMEOUT_SECONDS: float = 60.0
    # Figure/region explanation needs a vision-capable model; not every free
    # endpoint has one, so the feature is gated rather than assumed.
    LLM_SUPPORTS_VISION: bool = False

    # --- Storage ------------------------------------------------------------
    # Local filesystem for now. Swapping to S3 is a new StorageService subclass,
    # not a change to any caller. Deliberately outside /app: uvicorn --reload
    # watches the app bind mount, so PDFs written under it would restart the API.
    STORAGE_DIR: str = "/data/storage"

    # CORS origin for the Vite dev server.
    FRONTEND_ORIGIN: str = "http://localhost:5173"

    # --- Auth -----------------------------------------------------------
    # Google Sign-In verifies the ID token's audience against this.
    GOOGLE_CLIENT_ID: str = ""
    # Signs our own session JWT, issued after a Google token verifies.
    JWT_SECRET: str = ""
    JWT_EXPIRES_DAYS: int = 30
    # Comma-separated allowlist gating who can actually get an account, since
    # anyone with a Google account can otherwise complete the OAuth flow.
    # Empty means "anyone with a valid Google token" — set this before
    # sharing the URL outside people you already trust individually.
    ALLOWED_EMAILS: str = ""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


# Import this singleton everywhere; instantiated once at process start.
settings = Settings()
