import base64
import json

import httpx
from pydantic import BaseModel

from app.config import Settings
from app.errors import ModelError
from app.models.providers.base import ImageInput, http_model_error, sse_events, stream_errors


class MuseProvider:
    name = "muse"

    def __init__(self, settings: Settings, client: httpx.Client | None = None):
        self.chat_context_tokens = settings.chat_context_tokens
        self.chat_image_token_reserve = settings.chat_image_token_reserve
        self.model = settings.muse_main_model
        self.client = client or httpx.Client(
            base_url="https://api.meta.ai/v1/",
            headers={"Authorization": f"Bearer {settings.muse_api_key.get_secret_value()}"},
            timeout=httpx.Timeout(settings.model_timeout_seconds, connect=10),
            transport=httpx.HTTPTransport(retries=0),
        )

    @staticmethod
    def _content(context, images):
        content = [{"type": "input_text", "text": json.dumps(context, ensure_ascii=False)}]
        for image in images:
            content.append({"type": "input_text", "text": image.label})
            encoded = base64.b64encode(image.data).decode("ascii")
            content.append(
                {"type": "input_image", "image_url": f"data:{image.content_type};base64,{encoded}"}
            )
        return content

    def stream_text(
        self, *, system: str, context: dict, images: list[ImageInput], max_output_tokens: int
    ):
        """Responses streaming: answer deltas, then response.completed or a failure event."""
        body = {
            "model": self.model,
            "instructions": system,
            "input": [{"role": "user", "content": self._content(context, images)}],
            "max_output_tokens": max_output_tokens,
            "stream": True,
            "store": False,
        }
        return stream_errors(self._stream(body))

    def _stream(self, body):
        with self.client.stream("POST", "responses", json=body) as response:
            if response.is_error:
                response.read()
                raise http_model_error(response)
            for event in sse_events(response):
                kind = event.get("type") if event else None
                if kind == "response.output_text.delta":
                    if event.get("delta"):
                        yield event["delta"]
                elif kind and kind.startswith("response.refusal"):
                    raise ModelError("refused")
                elif kind == "response.completed":
                    if (event.get("response") or {}).get("status", "completed") != "completed":
                        raise ModelError("truncated")
                    return
                elif kind == "response.incomplete":
                    raise ModelError("truncated")
                elif kind in {"response.failed", "error"}:
                    raise ModelError("provider_failed")
        raise ModelError("early_eof")

    def generate(
        self, *, system: str, context: dict, images: list[ImageInput], schema: type[BaseModel]
    ) -> dict:
        content = self._content(context, images)
        try:
            response = self.client.post(
                "responses",
                json={
                    "model": self.model,
                    "instructions": system,
                    "input": [{"role": "user", "content": content}],
                    "text": {
                        "format": {
                            "type": "json_schema",
                            "name": schema.__name__,
                            "schema": schema.model_json_schema(),
                            "strict": True,
                        }
                    },
                    "max_output_tokens": 6000,
                    "stream": False,
                    "store": False,
                },
            )
        except httpx.TimeoutException:
            raise ModelError("timeout") from None
        except httpx.TransportError:
            raise ModelError("transport") from None
        if response.is_error:
            raise http_model_error(response)
        try:
            body = response.json()
            if body["status"] != "completed":
                raise ModelError("incomplete_or_refused")
            texts = []
            for item in body["output"]:
                if item["type"] == "reasoning":
                    continue
                if (
                    item["type"] != "message"
                    or item["role"] != "assistant"
                    or item["status"] != "completed"
                ):
                    raise ModelError("incomplete_or_refused")
                for block in item["content"]:
                    if block["type"] != "output_text":
                        raise ModelError("incomplete_or_refused")
                    texts.append(block["text"])
            result = json.loads("".join(texts))
            if not isinstance(result, dict):
                raise ValueError("Expected object")
            return result
        except (KeyError, IndexError, TypeError, ValueError):
            raise ModelError("invalid_response") from None

    def close(self):
        self.client.close()
