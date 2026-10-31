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
