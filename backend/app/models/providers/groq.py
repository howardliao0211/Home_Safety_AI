import base64
import json

import httpx
from pydantic import BaseModel

from app.config import Settings
from app.errors import ModelError
from app.models.providers.base import ImageInput, http_model_error, sse_events, stream_errors


class GroqProvider:
    name = "groq"

    def __init__(self, settings: Settings, client: httpx.Client | None = None):
        self.chat_context_tokens = settings.chat_context_tokens
        self.chat_image_token_reserve = settings.chat_image_token_reserve
        self.model = settings.groq_model
        self.client = client or httpx.Client(
            base_url="https://api.groq.com/openai/v1/",
            headers={"Authorization": f"Bearer {settings.groq_api_key.get_secret_value()}"},
            timeout=httpx.Timeout(settings.model_timeout_seconds, connect=10),
            transport=httpx.HTTPTransport(retries=0),
        )

    @staticmethod
    def _content(context, images):
        content = [{"type": "text", "text": json.dumps(context, ensure_ascii=False)}]
        for image in images:
            content.append({"type": "text", "text": image.label})
            encoded = base64.b64encode(image.data).decode("ascii")
            content.append(
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:{image.content_type};base64,{encoded}"},
                }
            )
        return content

    def stream_text(
        self, *, system: str, context: dict, images: list[ImageInput], max_output_tokens: int
    ):
        """Plain chat completion streaming (Structured Outputs cannot stream on Groq)."""
        body = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": self._content(context, images)},
            ],
            "max_completion_tokens": max_output_tokens,
            "stream": True,
        }
        return stream_errors(self._stream(body))

    def _stream(self, body):
        with self.client.stream("POST", "chat/completions", json=body) as response:
            if response.is_error:
                response.read()
                raise http_model_error(response)
            for event in sse_events(response):
                if event is None:  # [DONE] without a finish reason.
                    break
                if event.get("error"):
                    raise ModelError("provider_failed")
                for choice in event.get("choices") or []:
                    delta = choice.get("delta") or {}
                    if delta.get("refusal"):
                        raise ModelError("refused")
                    if delta.get("content"):
                        yield delta["content"]
                    reason = choice.get("finish_reason")
                    if reason == "stop":
                        return
                    if reason == "length":
                        raise ModelError("truncated")
                    if reason:
                        raise ModelError(
                            "refused" if reason == "content_filter" else "provider_failed"
                        )
        raise ModelError("early_eof")

    def generate(
        self, *, system: str, context: dict, images: list[ImageInput], schema: type[BaseModel]
    ) -> dict:
        content = self._content(context, images)
        try:
            response = self.client.post(
                "chat/completions",
                json={
                    "model": self.model,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": content},
                    ],
                    "response_format": {
                        "type": "json_schema",
                        "json_schema": {
                            "name": schema.__name__,
                            "strict": True,
                            "schema": schema.model_json_schema(),
                        },
                    },
                    "max_completion_tokens": 6000,
                    "stream": False,
                },
            )
        except httpx.TimeoutException:
            raise ModelError("timeout") from None
        except httpx.TransportError:
            raise ModelError("transport") from None
        if response.is_error:
            raise http_model_error(response)
        try:
            choice = response.json()["choices"][0]
            if choice["finish_reason"] != "stop" or choice["message"].get("refusal"):
                raise ModelError("incomplete_or_refused")
            result = json.loads(choice["message"]["content"])
            if not isinstance(result, dict):
                raise ValueError("Expected object")
            return result
        except (KeyError, IndexError, TypeError, ValueError):
            raise ModelError("invalid_response") from None

    def close(self):
        self.client.close()
