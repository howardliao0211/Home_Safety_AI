import json

import httpx
import pytest
from conftest import assessment_result

from app.config import Settings
from app.errors import ModelError
from app.models.providers.base import ImageInput
from app.models.providers.muse import MuseProvider
from app.models.schemas import AssessmentResult


def completed(result):
    return {
        "status": "completed",
        "output": [
            {"type": "reasoning", "summary": []},
            {
                "type": "message",
                "role": "assistant",
                "status": "completed",
                "content": [{"type": "output_text", "text": json.dumps(result)}],
            },
        ],
    }


def test_muse_assesses_private_images_using_responses_and_strict_schema():
    def respond(request):
        assert str(request.url) == "https://api.meta.ai/v1/responses"
        assert request.headers["Authorization"] == "Bearer test-muse-key"
        payload = json.loads(request.content)
        assert payload["model"] == "test-muse-model"
        assert payload["stream"] is False and payload["store"] is False
        assert payload["instructions"] == "Safety rules"
        assert payload["text"]["format"]["type"] == "json_schema"
        assert payload["text"]["format"]["strict"] is True
        assert payload["text"]["format"]["schema"]["additionalProperties"] is False
        assert "response_format" not in payload
        content = payload["input"][0]["content"]
        assert json.loads(content[0]["text"]) == {"profiles": ["Pet"]}
        assert content[1:] == [
            {"type": "input_text", "text": "Initial room"},
            {"type": "input_image", "image_url": "data:image/jpeg;base64,cm9vbQ=="},
            {"type": "input_text", "text": "New evidence"},
            {"type": "input_image", "image_url": "data:image/png;base64,bmV3"},
        ]
        return httpx.Response(200, json=completed(assessment_result()))

    client = httpx.Client(
        base_url="https://api.meta.ai/v1/",
        headers={"Authorization": "Bearer test-muse-key"},
        transport=httpx.MockTransport(respond),
    )
    settings = Settings(
        _env_file=None,
        model_provider="muse",
        muse_api_key="test-muse-key",
        muse_main_model="test-muse-model",
    )
    provider = MuseProvider(settings, client)
    try:
        result = provider.generate(
            system="Safety rules",
            context={"profiles": ["Pet"]},
            images=[
                ImageInput("Initial room", "image/jpeg", b"room"),
                ImageInput("New evidence", "image/png", b"new"),
            ],
            schema=AssessmentResult,
        )
        assert AssessmentResult.model_validate(result).findings
    finally:
        provider.close()


@pytest.mark.parametrize(
    "failure,category", [(httpx.ReadTimeout, "timeout"), (httpx.ConnectError, "transport")]
)
def test_muse_transport_failure_is_safe_without_retry(failure, category):
    calls = []

    def respond(request):
        calls.append(request)
        raise failure("private payload", request=request)

    config = Settings(
        _env_file=None, model_provider="muse", muse_api_key="test-key", muse_main_model="test-model"
    )
    provider = MuseProvider(
        config,
        httpx.Client(base_url="https://example.test/", transport=httpx.MockTransport(respond)),
    )
    try:
        with pytest.raises(ModelError, match=category):
            provider.generate(system="rules", context={}, images=[], schema=AssessmentResult)
        assert len(calls) == 1
    finally:
        provider.close()


@pytest.mark.parametrize(
    "status,body,category",
    [
        (401, {"error": "private credentials"}, "upstream_http"),
        (402, {}, "upstream_http"),
        (429, {}, "upstream_http"),
        (503, {}, "upstream_http"),
        (200, {"status": "incomplete", "output": []}, "incomplete_or_refused"),
        (200, {"status": "failed", "error": "private details"}, "incomplete_or_refused"),
        (
            200,
            {
                "status": "completed",
                "output": [
                    {
                        "type": "message",
                        "role": "assistant",
                        "status": "completed",
                        "content": [{"type": "refusal", "refusal": "private"}],
                    }
                ],
            },
            "incomplete_or_refused",
        ),
        (200, completed([]), "invalid_response"),
        (200, {"status": "completed", "output": []}, "invalid_response"),
        (200, {"status": "completed", "output": None}, "invalid_response"),
        (200, [], "invalid_response"),
    ],
)
def test_muse_errors_are_safe_and_do_not_retry(status, body, category):
    calls = []

    def respond(request):
        calls.append(request)
        return httpx.Response(status, json=body)

    config = Settings(
        _env_file=None, model_provider="muse", muse_api_key="test-key", muse_main_model="test-model"
    )
    client = httpx.Client(base_url="https://example.test/", transport=httpx.MockTransport(respond))
    provider = MuseProvider(config, client)
    try:
        with pytest.raises(ModelError) as error:
            provider.generate(system="rules", context={}, images=[], schema=AssessmentResult)
        assert error.value.category == category
        assert "private" not in str(error.value)
        assert len(calls) == 1
    finally:
        provider.close()
