import json

import httpx
import pytest
from conftest import assessment_result
from pydantic import ValidationError

from app.config import Settings
from app.errors import ModelError
from app.models.providers.base import ImageInput
from app.models.providers.factory import build_provider
from app.models.providers.groq import GroqProvider
from app.models.schemas import AssessmentResult, RevisionResult


def test_groq_sends_private_photo_and_strict_schema(settings):
    sent = []

    def respond(request):
        sent.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"content": json.dumps(assessment_result())},
                    }
                ]
            },
        )

    client = httpx.Client(base_url="https://example.test/", transport=httpx.MockTransport(respond))
    provider = GroqProvider(settings, client)
    result = provider.generate(
        system="rules",
        context={"profiles": ["Pet"]},
        images=[ImageInput("Room", "image/jpeg", b"image")],
        schema=AssessmentResult,
    )
    assert AssessmentResult.model_validate(result).findings
    payload = sent[0]
    assert payload["model"] == "test-model" and payload["stream"] is False
    assert payload["max_completion_tokens"] == 6000
    assert "max_tokens" not in payload
    assert payload["response_format"]["json_schema"]["strict"] is True
    assert (
        payload["messages"][1]["content"][-1]["image_url"]["url"]
        == "data:image/jpeg;base64,aW1hZ2U="
    )
    assert len(sent) == 1


@pytest.mark.parametrize("schema", [AssessmentResult, RevisionResult])
def test_every_model_output_property_is_required_in_strict_schema(schema):
    def visit(value):
        if isinstance(value, dict):
            if value.get("type") == "object":
                assert value["additionalProperties"] is False
                assert set(value["required"]) == set(value["properties"])
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(schema.model_json_schema())


@pytest.mark.parametrize(
    "status,body,category",
    [
        (401, {"error": "private-key-and-image-body"}, "upstream_http"),
        (429, {}, "upstream_http"),
        (401, {"error": "Invalid API key: private-key-and-image-body"}, "upstream_http"),
        (400, {"error": "Unsupported model"}, "upstream_http"),
        (
            200,
            {"choices": [{"finish_reason": "length", "message": {"content": "{}"}}]},
            "incomplete_or_refused",
        ),
        (
            200,
            {"choices": [{"finish_reason": "stop", "message": {"content": "not JSON"}}]},
            "invalid_response",
        ),
        (200, {"choices": []}, "invalid_response"),
    ],
)
def test_provider_failure_has_safe_diagnostics_and_no_retry(settings, status, body, category):
    calls = []

    def respond(request):
        calls.append(request)
        return httpx.Response(status, json=body)

    client = httpx.Client(base_url="https://example.test/", transport=httpx.MockTransport(respond))
    with pytest.raises(ModelError) as error:
        GroqProvider(settings, client).generate(
            system="rules", context={}, images=[], schema=AssessmentResult
        )
    assert error.value.category == category
    assert "private" not in str(error.value) and len(calls) == 1


def test_timeout_has_no_automatic_retry(settings):
    calls = []

    def respond(request):
        calls.append(request)
        raise httpx.ReadTimeout("private request details", request=request)

    client = httpx.Client(base_url="https://example.test/", transport=httpx.MockTransport(respond))
    with pytest.raises(ModelError, match="timeout"):
        GroqProvider(settings, client).generate(
            system="rules", context={}, images=[], schema=AssessmentResult
        )
    assert len(calls) == 1


def test_muse_requires_its_own_credentials_without_falling_back_to_groq():
    with pytest.raises(ValidationError, match="MUSE_API_KEY"):
        Settings(
            _env_file=None, model_provider="muse", groq_api_key="groq-only", groq_model="groq-model"
        )
    with pytest.raises(ValidationError, match="MUSE_MAIN_MODEL") as error:
        Settings(_env_file=None, model_provider="muse", muse_api_key="private-muse-key")
    assert "private-muse-key" not in str(error.value)


def test_muse_factory_targets_meta_using_backend_key(monkeypatch):
    from app.models.providers.muse import MuseProvider

    def respond(request):
        assert str(request.url) == "https://api.meta.ai/v1/responses"
        assert request.headers["Authorization"] == "Bearer test-muse-key"
        assert json.loads(request.content)["model"] == "test-muse-model"
        return httpx.Response(429)

    monkeypatch.setattr(httpx, "HTTPTransport", lambda **kwargs: httpx.MockTransport(respond))
    provider = build_provider(
        Settings(
            _env_file=None,
            model_provider="muse",
            muse_api_key="test-muse-key",
            muse_main_model="test-muse-model",
        )
    )
    try:
        assert isinstance(provider, MuseProvider) and provider.name == "muse"
        with pytest.raises(ModelError) as error:
            provider.generate(system="rules", context={}, images=[], schema=AssessmentResult)
        assert error.value.upstream_status == 429
    finally:
        provider.close()


def test_production_disallows_emulators_and_requires_durable_cleanup():
    with pytest.raises(ValidationError, match="Durable account cleanup"):
        Settings(
            _env_file=None,
            environment="production",
            model_provider="muse",
            muse_api_key="test-key",
            muse_main_model="test-model",
        )
    with pytest.raises(ValidationError, match="Emulator endpoints"):
        Settings(
            _env_file=None,
            environment="production",
            annotation_worker_url="https://worker.test",
            annotation_worker_service_account="worker@test",
            annotation_tasks_queue="queue",
            model_provider="muse",
            muse_api_key="test-key",
            muse_main_model="test-model",
            firestore_emulator_host="127.0.0.1:8080",
        )


def test_config_errors_do_not_expose_secret_values():
    with pytest.raises(ValidationError) as error:
        Settings(_env_file=None, groq_api_key="private-api-key", groq_model="")
    assert "private-api-key" not in str(error.value)


def test_default_groq_client_targets_groq_with_backend_key(settings, monkeypatch):
    calls = []

    def respond(request):
        calls.append(request)
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"content": json.dumps(assessment_result())},
                    }
                ]
            },
        )

    monkeypatch.setattr(httpx, "HTTPTransport", lambda **kwargs: httpx.MockTransport(respond))
    provider = build_provider(settings)
    try:
        provider.generate(system="rules", context={}, images=[], schema=AssessmentResult)
    finally:
        provider.close()
    assert provider.name == "groq"
    assert str(calls[0].url) == "https://api.groq.com/openai/v1/chat/completions"
    assert calls[0].headers["Authorization"] == "Bearer test-key"
