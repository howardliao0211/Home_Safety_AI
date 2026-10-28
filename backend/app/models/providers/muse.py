import base64
import json

import httpx
from pydantic import BaseModel

from app.config import Settings
from app.errors import ModelError
from app.models.providers.base import ImageInput


class MuseProvider:
    name = "muse"

    def __init__(self, settings: Settings, client: httpx.Client | None = None):
        self.model = settings.muse_main_model
        self.client = client or httpx.Client(
            base_url="https://api.meta.ai/v1/",
            headers={"Authorization": f"Bearer {settings.muse_api_key.get_secret_value()}"},
            timeout=httpx.Timeout(settings.model_timeout_seconds, connect=10),
            transport=httpx.HTTPTransport(retries=0),
        )

    def generate(
        self, *, system: str, context: dict, images: list[ImageInput], schema: type[BaseModel]
    ) -> dict:
        content = [{"type": "input_text", "text": json.dumps(context, ensure_ascii=False)}]
        for image in images:
            content.append({"type": "input_text", "text": image.label})
            encoded = base64.b64encode(image.data).decode("ascii")
            content.append(
                {"type": "input_image", "image_url": f"data:{image.content_type};base64,{encoded}"}
            )
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
            raise ModelError("upstream_http", upstream_status=response.status_code)
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
