import base64
import io
import json
import time

import httpx
import pytest
from PIL import Image

from app.errors import ModelError
from app.room_concepts.provider import MuseRoomProvider


@pytest.mark.parametrize("encoding", ["JPEG", "PNG", "WEBP"])
def test_edits_reference_photo_with_configured_model(settings, photo_bytes, encoding):
    output = io.BytesIO()
    with Image.open(io.BytesIO(photo_bytes)) as source:
        source.save(output, encoding)
    response_bytes = output.getvalue()
    settings.muse_image_gen_model = "chosen-image-model"
    settings.muse_api_key = "image-key"
    requests = []

    def respond(request):
        assert str(request.url) == "https://api.meta.ai/v1/responses"
        assert request.headers["Authorization"] == "Bearer image-key"
        requests.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "status": "completed",
                "output": [
                    {"type": "reasoning"},
                    {
                        "type": "image_generation_call",
                        "status": "completed",
                        "result": base64.b64encode(response_bytes).decode(),
                    },
                ],
            },
        )

    provider = MuseRoomProvider(settings, transport=httpx.MockTransport(respond))
    image, width, height = provider.generate(
        "Edit this room",
        photo_bytes,
        "image/png",
        deadline=time.monotonic() + 20,
    )
    assert width == 100 and height == 60
    assert image.startswith(b"\xff\xd8")  # Validated/re-encoded JPEG, not raw provider bytes.
    body = requests[0]
    assert body["model"] == "chosen-image-model"
    assert body["store"] is False
    assert body["input"][0]["content"][1]["image_url"].startswith("data:image/png;base64,")
    assert body["tools"][0]["enable_web_search"] is False
    assert body["tools"][0]["enable_image_search"] is False
    assert body["tools"][0]["enable_shell"] is False


@pytest.mark.parametrize(
    "payload",
    [
        {"status": "completed", "output": []},
        {"status": "incomplete", "output": []},
        {
            "status": "completed",
            "output": [{"type": "image_generation_call", "status": "completed", "result": "bad!!"}],
        },
        {
            "status": "completed",
            "output": [
                {
                    "type": "image_generation_call",
                    "status": "completed",
                    "result": "bm90IGFuIGltYWdl",
                }
            ],
        },
    ],
)
def test_invalid_output_fails_without_retry(settings, payload):
    calls = []

    def respond(request):
        calls.append(request)
        return httpx.Response(200, json=payload)

    provider = MuseRoomProvider(settings, transport=httpx.MockTransport(respond))
    with pytest.raises(ModelError):
        provider.generate("edit", b"photo", "image/jpeg", deadline=time.monotonic() + 5)
    assert len(calls) == 1


def test_overall_deadline_bounds_slow_provider(settings):
    import asyncio

    async def slow(request):
        await asyncio.sleep(1)
        return httpx.Response(200, json={})

    provider = MuseRoomProvider(settings, transport=httpx.MockTransport(slow))
    started = time.monotonic()
    with pytest.raises(ModelError, match="image_timeout"):
        provider.generate("edit", b"image", "image/jpeg", deadline=started + 0.02)
    assert time.monotonic() - started < 0.5


def test_provider_errors_never_retry_or_leak_bodies(settings):
    calls = []

    def unavailable(request):
        calls.append(request)
        return httpx.Response(503, text="private credentials and photo payload")

    provider = MuseRoomProvider(settings, transport=httpx.MockTransport(unavailable))
    with pytest.raises(ModelError) as error:
        provider.generate("edit", b"image", "image/jpeg", deadline=time.monotonic() + 2)
    assert error.value.upstream_status == 503
    assert "private" not in str(error.value)
    assert len(calls) == 1


def test_animated_image_is_still_rejected(settings):
    output = io.BytesIO()
    Image.new("RGB", (100, 60), "red").save(
        output,
        "PNG",
        save_all=True,
        append_images=[Image.new("RGB", (100, 60), "blue")],
        duration=100,
    )

    def respond(request):
        return httpx.Response(
            200,
            json={
                "status": "completed",
                "output": [
                    {
                        "type": "image_generation_call",
                        "status": "completed",
                        "result": base64.b64encode(output.getvalue()).decode(),
                    }
                ],
            },
        )

    provider = MuseRoomProvider(settings, transport=httpx.MockTransport(respond))
    with pytest.raises(ModelError, match="invalid_image_output"):
        provider.generate("edit", b"photo", "image/jpeg", deadline=time.monotonic() + 5)
