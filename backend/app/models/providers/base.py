from collections.abc import Iterator
from dataclasses import dataclass
from typing import Protocol

from pydantic import BaseModel


@dataclass(frozen=True)
class ImageInput:
    label: str
    content_type: str
    data: bytes


class ModelProvider(Protocol):
    name: str
    model: str

    def generate(
        self,
        *,
        system: str,
        context: dict,
        images: list[ImageInput],
        schema: type[BaseModel],
    ) -> dict:
        """Return JSON data. The controller validates it before any state update.

        Raise ModelError with safe metadata on transport, refusal, or output failure.
        No retries or persistence belong in the adapter.
        """
        ...

    def stream_text(
        self,
        *,
        system: str,
        context: dict,
        images: list[ImageInput],
        max_output_tokens: int,
    ) -> Iterator[str]:
        """Yield plain answer-text fragments for finding chat.

        Return normally only after the provider's explicit success event. Raise
        ModelError (refused, truncated, early_eof, provider_failed, timeout,
        transport, context_limit, ...) otherwise; never retry.
        """
        ...

    def close(self) -> None: ...


def http_model_error(response):
    """Classify capacity without exposing provider response bodies."""
    from app.errors import ModelError

    try:
        code = response.json().get("error", {}).get("code")
    except (ValueError, AttributeError, TypeError):
        code = None
    category = (
        "context_limit"
        if code
        in {
            "context_length_exceeded",
            "context_window_exceeded",
            "input_too_long",
            "max_context_length_exceeded",
        }
        else "upstream_http"
    )
    return ModelError(category, upstream_status=response.status_code)


def sse_events(response, limit=2_000_000):
    """Parse `data:` lines of a server-sent event stream as JSON (`[DONE]` ends it)."""
    import json

    from app.errors import ModelError

    total = 0
    for line in response.iter_lines():
        total += len(line)
        if total > limit:
            raise ModelError("invalid_response")
        if not line.startswith("data:"):
            continue
        payload = line[5:].strip()
        if payload == "[DONE]":
            yield None
            return
        try:
            yield json.loads(payload)
        except ValueError:
            raise ModelError("invalid_response") from None


def stream_errors(stream):
    """Map transport failures during a stream to safe categories."""
    import httpx

    from app.errors import ModelError

    try:
        yield from stream
    except httpx.TimeoutException:
        raise ModelError("timeout") from None
    except httpx.TransportError:
        raise ModelError("transport") from None
