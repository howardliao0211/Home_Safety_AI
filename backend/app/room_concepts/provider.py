"""One-shot Muse room edits. Never retries or persists provider conversation state."""

import asyncio
import base64
import io
import json
import time
import warnings

import httpx
from PIL import Image, ImageOps

from app.annotations.budget import bounded_cpu
from app.errors import ModelError

MAX_IMAGE_BYTES = 10 * 1024 * 1024
MAX_RESPONSE_BYTES = 15 * 1024 * 1024
MAX_PIXELS = 20_000_000


def decode_image(payload):
    if payload.get("status") != "completed":
        raise ValueError("Incomplete response")
    items = [o for o in payload.get("output", []) if o.get("type") == "image_generation_call"]
    if len(items) != 1 or items[0].get("status") != "completed":
        raise ValueError("Expected one completed image")
    encoded = items[0].get("result")
    if not isinstance(encoded, str) or len(encoded) > ((MAX_IMAGE_BYTES + 2) // 3) * 4:
        raise ValueError("Invalid image size")
    data = base64.b64decode(encoded, validate=True)
    if not data or len(data) > MAX_IMAGE_BYTES:
        raise ValueError("Invalid image size")
    with warnings.catch_warnings():
        warnings.simplefilter("error", Image.DecompressionBombWarning)
        with Image.open(io.BytesIO(data)) as source:
            if source.format not in {"JPEG", "PNG", "WEBP"} or source.is_animated:
                raise ValueError("Unsupported image")
            if source.width * source.height > MAX_PIXELS:
                raise ValueError("Image too large")
            source.load()
            image = ImageOps.exif_transpose(source).convert("RGB")
            output = io.BytesIO()
            image.save(output, "JPEG", quality=90)
            clean = output.getvalue()
            if len(clean) > MAX_IMAGE_BYTES:
                raise ValueError("Image too large")
            return clean, image.width, image.height


class MuseRoomProvider:
    def __init__(self, settings, *, transport=None):
        self.model = settings.muse_image_gen_model.strip()
        key = settings.muse_api_key
        self.key = key.get_secret_value() if hasattr(key, "get_secret_value") else str(key or "")
        self.transport = transport

    def generate(self, prompt, photo, content_type, *, deadline):
        async def run():
            return await asyncio.wait_for(
                self._generate(prompt, photo, content_type, deadline),
                timeout=max(0.01, deadline - time.monotonic()),
            )

        try:
            return asyncio.run(run())
        except TimeoutError:
            raise ModelError("image_timeout") from None

    async def _generate(self, prompt, photo, content_type, deadline):
        body = {
            "model": self.model,
            "store": False,
            "input": [
                {
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": prompt},
                        {
                            "type": "input_image",
                            "image_url": f"data:{content_type};base64,"
                            + base64.b64encode(photo).decode(),
                        },
                    ],
                }
            ],
            "tools": [
                {
                    "type": "image_generation",
                    "enable_image_search": False,
                    "enable_web_search": False,
                    "enable_shell": False,
                    "output_format": "jpeg",
                }
            ],
        }
        category = "image_transport"
        try:
            # Stream a bounded response to avoid trusting Content-Length. Each read
            # also checks the overall budget; no SDK automatic retries are involved.
            async with httpx.AsyncClient(transport=self.transport) as client:
                async with client.stream(
                    "POST",
                    "https://api.meta.ai/v1/responses",
                    headers={"Authorization": "Bearer " + self.key},
                    json=body,
                    timeout=max(0.01, deadline - time.monotonic()),
                ) as response:
                    response.raise_for_status()
                    data = bytearray()
                    async for chunk in response.aiter_bytes():
                        if time.monotonic() >= deadline:
                            raise TimeoutError()
                        data.extend(chunk)
                        if len(data) > MAX_RESPONSE_BYTES:
                            raise ValueError("Response too large")
            category = "invalid_image_output"
            result = await bounded_cpu(decode_image, json.loads(data), deadline=deadline)
            if time.monotonic() >= deadline:
                raise TimeoutError()
            return result
        except Exception as exc:
            status = exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else None
            if status:
                category = {
                    401: "credentials_rejected",
                    403: "credentials_rejected",
                    429: "rate_limited",
                    400: "image_request_rejected",
                }.get(status, "image_upstream_error")
            elif isinstance(exc, (TimeoutError, httpx.TimeoutException)):
                category = "image_timeout"
            raise ModelError(category, upstream_status=status) from None
