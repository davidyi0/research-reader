"""One implementation covering every OpenAI-compatible endpoint.

Groq, Cerebras, OpenRouter, Ollama, Google's compat endpoint, and OpenAI all
speak this wire format, so they differ only by base URL, key, and model name.

Raw HTTP rather than the `openai` SDK: the SDK is a vendor client that happens
to accept a base_url, and pulling it in would quietly make one provider the
"real" one. This is ~150 lines and keeps the abstraction honest.
"""
import json
from typing import Any, AsyncIterator

import httpx

from app.services.llm.base import LLMConfigError, LLMRequestError

# Structured-output support varies a lot across compatible endpoints, so the
# provider walks down this ladder and remembers what worked.
_MODE_JSON_SCHEMA = "json_schema"  # strict schema enforcement (OpenAI, Groq)
_MODE_JSON_OBJECT = "json_object"  # "must be valid JSON", no schema (most others)
_MODE_PROMPT_ONLY = "prompt"  # ask nicely and parse (Ollama and friends)


class OpenAICompatProvider:
    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        timeout: float = 60.0,
        supports_vision: bool = False,
    ) -> None:
        if not model:
            raise LLMConfigError("LLM_MODEL is not set — check your .env.")
        self.model = model
        self.supports_vision = supports_vision
        self._base_url = base_url.rstrip("/")
        # Ollama needs no key; everything else does. Send the header regardless
        # when a key is present and let the provider decide.
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        self._client = httpx.AsyncClient(timeout=timeout, headers=headers)
        self._structured_mode: str | None = None

    # --- critical path ----------------------------------------------------

    async def stream(self, *, system: str, user: str) -> AsyncIterator[str]:
        """Yield content deltas as they arrive.

        Streaming is not optional here — time-to-first-token is what keeps the
        reader in flow, and a buffered response would defeat the whole product.
        """
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "stream": True,
        }
        async with self._client.stream(
            "POST", f"{self._base_url}/chat/completions", json=payload
        ) as response:
            if response.status_code >= 400:
                body = (await response.aread()).decode(errors="replace")
                raise LLMRequestError(
                    f"{response.status_code} from {self._base_url}: {body[:500]}"
                )
            async for line in response.aiter_lines():
                delta = _parse_sse_line(line)
                if delta is None:
                    continue
                if delta is _DONE:
                    return
                yield delta

    # --- off the critical path --------------------------------------------

    async def structured(self, *, system: str, user: str, schema: dict) -> dict:
        """Return parsed JSON, degrading gracefully as provider support allows."""
        modes = (
            [self._structured_mode]
            if self._structured_mode
            else [_MODE_JSON_SCHEMA, _MODE_JSON_OBJECT, _MODE_PROMPT_ONLY]
        )
        last_error: Exception | None = None

        for mode in modes:
            payload = _structured_payload(self.model, system, user, schema, mode)
            try:
                response = await self._client.post(
                    f"{self._base_url}/chat/completions", json=payload
                )
                if response.status_code == 400:
                    # Almost always "this endpoint doesn't support that
                    # response_format" — try the next rung down.
                    last_error = LLMRequestError(response.text[:500])
                    continue
                response.raise_for_status()
                content = response.json()["choices"][0]["message"]["content"]
                parsed = _extract_json(content)
                self._structured_mode = mode  # remember what this provider accepts
                return parsed
            except (httpx.HTTPError, KeyError, ValueError) as exc:
                last_error = exc
                continue

        raise LLMRequestError(f"structured output failed on all modes: {last_error}")

    async def aclose(self) -> None:
        await self._client.aclose()


# --- helpers --------------------------------------------------------------

_DONE = object()


def _parse_sse_line(line: str) -> Any:
    """Pull one content delta out of an SSE line.

    Returns the delta string, `_DONE` at end of stream, or None for anything
    that carries no content (keepalive comments, blank lines, the initial
    role-only chunk).
    """
    line = line.strip()
    if not line or not line.startswith("data:"):
        return None
    data = line[len("data:") :].strip()
    if data == "[DONE]":
        return _DONE
    try:
        chunk = json.loads(data)
    except json.JSONDecodeError:
        return None
    choices = chunk.get("choices") or []
    if not choices:
        return None
    return choices[0].get("delta", {}).get("content") or None


def _structured_payload(
    model: str, system: str, user: str, schema: dict, mode: str
) -> dict:
    payload: dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "stream": False,
    }
    if mode == _MODE_JSON_SCHEMA:
        payload["response_format"] = {
            "type": "json_schema",
            "json_schema": {"name": "result", "schema": schema, "strict": True},
        }
        return payload

    # Both weaker modes need the shape in the prompt instead. OpenAI's
    # json_object mode also requires the literal word "json" in the messages.
    payload["messages"][-1]["content"] = (
        f"{user}\n\nRespond with json matching this schema exactly, "
        f"and nothing else:\n{json.dumps(schema)}"
    )
    if mode == _MODE_JSON_OBJECT:
        payload["response_format"] = {"type": "json_object"}
    return payload


def _extract_json(content: str) -> dict:
    """Parse JSON out of a model response.

    Models in prompt-only mode habitually wrap JSON in ```json fences or add a
    sentence of preamble, so fall back to the outermost brace pair.
    """
    content = content.strip()
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        pass
    start, end = content.find("{"), content.rfind("}")
    if start == -1 or end <= start:
        raise ValueError(f"no JSON object in response: {content[:200]}")
    return json.loads(content[start : end + 1])
