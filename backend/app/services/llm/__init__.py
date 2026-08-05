"""LLM access for the whole app.

Import `get_provider()` — never construct a provider or talk to an endpoint
directly. Everything vendor-specific stops here.
"""
from app.core.config import settings
from app.services.llm.base import (
    LLMConfigError,
    LLMError,
    LLMProvider,
    LLMRequestError,
    estimate_tokens,
)
from app.services.llm.openai_compat import OpenAICompatProvider

__all__ = [
    "LLMConfigError",
    "LLMError",
    "LLMProvider",
    "LLMRequestError",
    "estimate_tokens",
    "get_provider",
    "close_provider",
]

_provider: OpenAICompatProvider | None = None


def get_provider() -> OpenAICompatProvider:
    """The configured provider, constructed once and reused.

    One long-lived HTTP client matters here: a fresh connection per request
    adds a TLS handshake to time-to-first-token, which is the metric this
    product lives or dies on.
    """
    global _provider
    if _provider is None:
        _provider = OpenAICompatProvider(
            base_url=settings.LLM_BASE_URL,
            api_key=settings.LLM_API_KEY,
            model=settings.LLM_MODEL,
            timeout=settings.LLM_TIMEOUT_SECONDS,
            supports_vision=settings.LLM_SUPPORTS_VISION,
        )
    return _provider


async def close_provider() -> None:
    """Release the HTTP client. Wired into the FastAPI lifespan."""
    global _provider
    if _provider is not None:
        await _provider.aclose()
        _provider = None
