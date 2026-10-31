import base64
import json

import httpx
from pydantic import BaseModel

from app.config import Settings
from app.errors import ModelError
from app.models.providers.base import ImageInput, http_model_error


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

    def generate(
        self, *, system: str, context: dict, images: list[ImageInput], schema: type[BaseModel]
    ) -> dict:
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
