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
