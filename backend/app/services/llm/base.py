"""Provider-agnostic LLM contract.

Nothing above this package knows which model or vendor is configured. That is
the point: the app is developed against a free OpenAI-compatible endpoint and
can be pointed at a frontier model with an env change.

Two operations, deliberately. `stream` is the critical path (latency is the
product), `structured` is for off-path extraction work.
"""
from typing import AsyncIterator, Protocol, runtime_checkable


class LLMError(RuntimeError):
    """Base for anything that goes wrong talking to a provider."""


class LLMConfigError(LLMError):
    """Provider is not configured — missing key, missing model."""


class LLMRequestError(LLMError):
    """Provider returned an error or an unparseable response."""


@runtime_checkable
class LLMProvider(Protocol):
    """The whole surface the rest of the app is allowed to depend on."""

    model: str
    supports_vision: bool

    def stream(self, *, system: str, user: str) -> AsyncIterator[str]:
        """Yield response text incrementally. Drives the explanation card."""
        ...

    async def structured(self, *, system: str, user: str, schema: dict) -> dict:
        """Return JSON conforming to `schema`.

        Returns a parsed dict; validating it against the schema is the caller's
        job, since the caller is what defines the schema and knows the type it
        wants back.
        """
        ...

    async def aclose(self) -> None:
        ...


def estimate_tokens(text: str) -> int:
    """Rough token count for context budgeting.

    Deliberately approximate. There is no correct tokenizer here — the model
    behind LLM_BASE_URL could be Llama, Qwen, Gemini, or GPT, and `tiktoken`
    (OpenAI's) is materially wrong for all but the last. A budget guard only
    needs to be in the right ballpark, so ~4 chars/token it is.
    """
    return len(text) // 4
