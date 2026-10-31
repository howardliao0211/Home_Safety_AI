from uuid import uuid4

import pytest


def chat_path(assessment):
    return f"/v1/assessments/{assessment['id']}/findings/{assessment['findings'][0]['id']}/chat"


@pytest.mark.parametrize("status", ["open", "resolved", "dismissed"])
def test_chat_is_saved_idempotent_and_advisory(rig, assessed, status):
    client, repo, photos, provider = rig
    path = chat_path(assessed)
    client.patch(path.removesuffix("/chat"), json={"status": status})
    before = client.get(f"/v1/assessments/{assessed['id']}").json()
    calls = len(provider.calls)
    assert client.get(path).json()["turns"] == []
    assert len(provider.calls) == calls
    body = {"id": str(uuid4()), "question": "How can I keep this walkway clear?"}
    first = client.post(path + "/turns", json=body)
    assert first.status_code == 201, first.text
    assert first.json()["turns"][0]["status"] == "ready"
    assert client.post(path + "/turns", json=body).json() == first.json()
    assert client.post(path + "/turns", json={**body, "question": "Different"}).status_code == 409
    provider.results.append({"answer": "Keep cables away from the walking route if safe."})
    url = path + "/turns/" + body["id"] + "/generate"
    attempt = str(uuid4())
    result = client.post(url, json={"attempt_id": attempt})
    assert result.status_code == 200, result.text
    assert result.json()["turns"][0]["answer"].startswith("Keep cables")
    assert client.post(url, json={"attempt_id": attempt}).json() == result.json()
    assert len(provider.calls) == calls + 1
    assert client.get(path).json() == result.json()
    assert client.get(f"/v1/assessments/{assessed['id']}").json() == before


def send(client, path, text="What should I do?"):
    body = {"id": str(uuid4()), "question": text}
    response = client.post(path + "/turns", json=body)
    assert response.status_code == 201, response.text
    return body["id"]


def generate(client, path, tid, attempt=None):
    return client.post(
        path + f"/turns/{tid}/generate", json={"attempt_id": attempt or str(uuid4())}
    )


def test_saved_history_current_status_and_original_photo_are_context(rig, assessed):
    from conftest import content

    client, _, _, provider = rig
    path = chat_path(assessed)
    # Legacy completed discussion remains useful but its photo is not resent.
    fid_path = path.removesuffix("/chat")
    sid = str(uuid4())
    client.post(
        fid_path + "/submissions",
        data={"submission_id": sid, "kind": "follow-up", "text": "Used at night"},
    )
    provider.results.append({"finding": content(), "feedback": "Night use adds context."})
    client.post(fid_path + f"/submissions/{sid}/analyze")
    provider.results.append({"answer": "Keep the route clear."})
    tid = send(client, path, "How can I reduce trips?")
    assert generate(client, path, tid).status_code == 200
    client.patch(fid_path, json={"status": "resolved"})
    tid = send(client, path, "Does that also help at night?")
    provider.results.append({"answer": "Yes, but the photo cannot establish safety."})
    assert generate(client, path, tid).status_code == 200
    call = provider.calls[-1]
    assert call["context"]["finding"]["status"] == "resolved"
    assert call["context"]["profiles"] == ["Older adult", "Baby", "Pet"]
    assert call["context"]["previous_chat"] == [
        {"user": "How can I reduce trips?", "assistant": "Keep the route clear."}
    ]
    assert call["context"]["historical_discussion"][0]["user_text"] == "Used at night"
    assert (
        call["context"]["historical_discussion"][0]["assistant_question"]
        == "Is this route used at night?"
    )
    assert call["context"]["current_question"] == "Does that also help at night?"
    assert len(call["images"]) == 1


def test_failure_and_lost_responses_never_repeat_generation(rig, assessed):
    from app.errors import ModelError

    client, _, _, provider = rig
    path = chat_path(assessed)
    tid = send(client, path)
    attempt = str(uuid4())
    calls = len(provider.calls)
    provider.results.append(ModelError("timeout"))
    assert generate(client, path, tid, attempt).status_code == 502
    assert generate(client, path, tid, attempt).json()["turns"][0]["status"] == "failed"
    assert len(provider.calls) == calls + 1
    assert (
        client.post(path + "/turns", json={"id": str(uuid4()), "question": "Next?"}).status_code
        == 409
    )
    provider.results.append({"answer": "A saved reply."})
    assert generate(client, path, tid).json()["turns"][0]["answer"] == "A saved reply."
    assert len(client.get(path).json()["turns"]) == 1


def test_cross_device_pending_and_same_attempt_are_enforced(rig, assessed):
    client, _, _, provider = rig
    path = chat_path(assessed)
    tid = send(client, path)
    attempt = str(uuid4())
    calls = len(provider.calls)

    def during_call():
        assert generate(client, path, tid, attempt).json()["turns"][0]["status"] == "running"
        assert generate(client, path, tid).json()["turns"][0]["status"] == "running"
        assert (
            client.post(
                path + "/turns", json={"id": str(uuid4()), "question": "Concurrent?"}
            ).status_code
            == 409
        )

    provider.on_call = during_call
    provider.results.append({"answer": "Only one reply."})
    assert generate(client, path, tid, attempt).status_code == 200
    assert len(provider.calls) == calls + 1


def test_interruption_is_readable_after_restart_and_requires_explicit_retry(
    rig, assessed, settings
):
    from datetime import timedelta

    from fastapi.testclient import TestClient

    from app.main import create_app
    from app.models.schemas import now

    client, repo, photos, provider = rig
    path = chat_path(assessed)
    tid = send(client, path)

    def interrupt(a):
        t = a.findings[0].chat[0]
        t.status = "running"
        t.attempt_ids = [str(uuid4())]
        t.expires_at = now() - timedelta(seconds=1)
        return a

    repo.mutate(client.headers["X-Device-ID"], assessed["id"], interrupt)
    calls = len(provider.calls)
    with TestClient(create_app(settings, repo, photos, provider)) as restarted:
        restarted.headers["Authorization"] = client.headers["Authorization"]
        result = restarted.get(path).json()
        assert result["turns"][0]["status"] == "failed"
        assert "interrupted" in result["turns"][0]["error"]
        assert len(provider.calls) == calls
        provider.results.append({"answer": "Recovered reply."})
        assert generate(restarted, path, tid).status_code == 200


def test_chat_is_owner_scoped_and_cannot_resurrect_deleted_assessments(rig, assessed):
    client, _, _, provider = rig
    path = chat_path(assessed)
    tid = send(client, path)
    owner = client.headers["Authorization"]
    client.headers["Authorization"] = "Bearer " + str(uuid4())
    assert client.get(path).status_code == 404
    assert (
        client.post(
            path + "/turns", json={"id": str(uuid4()), "question": "Other account"}
        ).status_code
        == 404
    )
    assert generate(client, path, tid).status_code == 404
    client.headers["Authorization"] = owner

    def during_call():
        assert client.delete(f"/v1/assessments/{assessed['id']}").status_code == 204

    provider.on_call = during_call
    provider.results.append({"answer": "Must never resurrect."})
    assert generate(client, path, tid).status_code == 404
    assert client.get(path).status_code == 404


def test_blank_long_and_full_context_do_not_accept_questions(rig, assessed):
    client, repo, _, provider = rig
    path = chat_path(assessed)
    for text in ["  \n ", "x" * 2001]:
        assert (
            client.post(path + "/turns", json={"id": str(uuid4()), "question": text}).status_code
            == 422
        )

    def full(a):
        a.household_context = "x" * 25000
        return a

    repo.mutate(client.headers["X-Device-ID"], assessed["id"], full)
    calls = len(provider.calls)
    assert client.get(path).json()["blocked_reason"]
    assert (
        client.post(
            path + "/turns", json={"id": str(uuid4()), "question": "A question"}
        ).status_code
        == 409
    )
    assert len(provider.calls) == calls


def test_another_finding_history_is_excluded(rig, assessed):
    from conftest import content

    from app.models.schemas import Finding

    client, repo, _, provider = rig

    def other(a):
        a.findings.append(Finding(**content()))
        return a

    changed = repo.mutate(client.headers["X-Device-ID"], assessed["id"], other)
    first = chat_path(assessed)
    provider.results.append({"answer": "Private first discussion"})
    assert generate(client, first, send(client, first, "First question")).status_code == 200
    second = f"/v1/assessments/{assessed['id']}/findings/{changed.findings[1].id}/chat"
    provider.results.append({"answer": "Separate discussion"})
    assert generate(client, second, send(client, second)).status_code == 200
    assert provider.calls[-1]["context"]["previous_chat"] == []


def test_context_capacity_failure_is_not_a_transient_retry(rig, assessed):
    from app.errors import ModelError

    client, _, _, provider = rig
    path = chat_path(assessed)
    tid = send(client, path)
    provider.results.append(ModelError("context_limit"))
    assert generate(client, path, tid).status_code == 409
    result = client.get(path).json()
    assert result["blocked_reason"] and result["turns"][0]["question"]
    calls = len(provider.calls)
    assert generate(client, path, tid).status_code == 409
    assert len(provider.calls) == calls


@pytest.mark.parametrize("provider_name", ["groq", "muse"])
def test_provider_capacity_rejection_has_safe_non_transient_category(settings, provider_name):
    import httpx

    from app.assessments.chat import ChatAnswer
    from app.config import Settings
    from app.errors import ModelError
    from app.models.providers.groq import GroqProvider
    from app.models.providers.muse import MuseProvider

    config = (
        settings
        if provider_name == "groq"
        else Settings(
            _env_file=None, model_provider="muse", muse_api_key="test", muse_main_model="test"
        )
    )
    provider_type = GroqProvider if provider_name == "groq" else MuseProvider
    client = httpx.Client(
        base_url="https://example.test/",
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                400,
                json={
                    "error": {
                        "code": "context_length_exceeded",
                        "message": "private conversation text",
                    }
                },
            )
        ),
    )
    with pytest.raises(ModelError) as error:
        provider_type(config, client).generate(
            system="rules", context={}, images=[], schema=ChatAnswer
        )
    assert error.value.category == "context_limit"
    assert "private" not in str(error.value)


def test_last_accepted_question_can_still_retry_at_turn_limit(rig, assessed):
    from app.errors import ModelError

    client, _, _, provider = rig
    path = chat_path(assessed)
    for _ in range(11):
        provider.results.append({"answer": "Short reply."})
        assert generate(client, path, send(client, path)).status_code == 200
    tid = send(client, path, "Last question")
    provider.results.append(ModelError("timeout"))
    assert generate(client, path, tid).status_code == 502
    result = client.get(path).json()
    assert result["blocked_reason"]
    assert result["retry_blocked_reason"] is None
    provider.results.append({"answer": "Retried final reply."})
    assert generate(client, path, tid).json()["turns"][-1]["status"] == "complete"
