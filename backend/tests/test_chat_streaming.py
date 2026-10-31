import json

import httpx
import pytest

from app.config import Settings
from app.errors import ModelError
from app.models.providers.base import ImageInput
from app.models.providers.groq import GroqProvider
from app.models.providers.muse import MuseProvider


def sse(events, done=False):
    body = "".join("data: " + json.dumps(e) + "\n\n" for e in events)
    return body + ("data: [DONE]\n\n" if done else "")


def provider(kind, body, status=200, requests=None):
    def handle(request):
        if requests is not None:
            requests.append(json.loads(request.content))
        return httpx.Response(
            status,
            text=body if isinstance(body, str) else None,
            json=body if not isinstance(body, str) else None,
        )

    client = httpx.Client(base_url="https://example.test/", transport=httpx.MockTransport(handle))
    if kind == "muse":
        config = Settings(
            _env_file=None, model_provider="muse", muse_api_key="k", muse_main_model="m"
        )
        return MuseProvider(config, client)
    config = Settings(_env_file=None, groq_api_key="k", groq_model="m")
    return GroqProvider(config, client)


def stream(adapter):
    return list(
        adapter.stream_text(
            system="rules",
            context={"q": 1},
            images=[ImageInput("Original room photo", "image/jpeg", b"photo")],
            max_output_tokens=700,
        )
    )


MUSE_OK = [
    {"type": "response.created"},
    {"type": "response.reasoning_summary_text.delta", "delta": "hidden thinking"},
    {"type": "response.output_text.delta", "delta": "Keep the "},
    {"type": "response.output_text.delta", "delta": "route clear."},
    {"type": "response.completed", "response": {"status": "completed"}},
]
GROQ_OK = [
    {"choices": [{"delta": {"role": "assistant", "content": "Keep the "}, "finish_reason": None}]},
    {"choices": [{"delta": {"content": "route clear."}, "finish_reason": None}]},
    {"choices": [{"delta": {}, "finish_reason": "stop"}]},
]


def test_muse_streams_plain_text_with_photo_and_no_stored_history():
    requests = []
    assert stream(provider("muse", sse(MUSE_OK), requests=requests)) == [
        "Keep the ",
        "route clear.",
    ]
    body = requests[0]
    assert body["stream"] is True and body["store"] is False and "text" not in body
    assert body["max_output_tokens"] == 700
    assert body["input"][0]["content"][2]["type"] == "input_image"


def test_groq_streams_plain_text_without_structured_output():
    requests = []
    assert stream(provider("groq", sse(GROQ_OK, done=True), requests=requests)) == [
        "Keep the ",
        "route clear.",
    ]
    body = requests[0]
    assert body["stream"] is True and "response_format" not in body
    assert body["messages"][1]["content"][2]["type"] == "image_url"


@pytest.mark.parametrize(
    "events,category",
    [
        (MUSE_OK[:3], "early_eof"),
        (MUSE_OK[:3] + [{"type": "response.incomplete", "response": {}}], "truncated"),
        (MUSE_OK[:3] + [{"type": "response.refusal.delta", "delta": "no"}], "refused"),
        (MUSE_OK[:3] + [{"type": "response.failed", "response": {}}], "provider_failed"),
        (MUSE_OK[:3] + [{"type": "error", "code": "x"}], "provider_failed"),
    ],
)
def test_muse_unsuccessful_streams_raise_after_partial(events, category):
    received = []
    with pytest.raises(ModelError) as error:
        for fragment in provider("muse", sse(events)).stream_text(
            system="s", context={}, images=[], max_output_tokens=10
        ):
            received.append(fragment)
    assert error.value.category == category and received == ["Keep the "]


@pytest.mark.parametrize(
    "events,done,category",
    [
        (GROQ_OK[:2], True, "early_eof"),
        (GROQ_OK[:2], False, "early_eof"),
        (
            GROQ_OK[:2] + [{"choices": [{"delta": {}, "finish_reason": "length"}]}],
            True,
            "truncated",
        ),
        (
            GROQ_OK[:2] + [{"choices": [{"delta": {}, "finish_reason": "content_filter"}]}],
            True,
            "refused",
        ),
    ],
)
def test_groq_unsuccessful_streams_raise(events, done, category):
    with pytest.raises(ModelError) as error:
        stream(provider("groq", sse(events, done=done)))
    assert error.value.category == category


@pytest.mark.parametrize("kind", ["groq", "muse"])
def test_capacity_rejection_is_a_safe_non_transient_category(kind):
    body = {"error": {"code": "context_length_exceeded", "message": "private conversation text"}}
    with pytest.raises(ModelError) as error:
        stream(provider(kind, body, status=400))
    assert error.value.category == "context_limit" and "private" not in str(error.value)
