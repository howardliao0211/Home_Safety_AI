from datetime import timedelta
from uuid import uuid4

import pytest
from conftest import assessment_result, content
from fastapi.testclient import TestClient

from app.errors import ModelError
from app.main import create_app
from app.models.schemas import Lease, now


def base(assessment):
    return f"/v1/assessments/{assessment['id']}"


def finding_path(assessment):
    return f"{base(assessment)}/findings/{assessment['findings'][0]['id']}"


def test_create_analyze_and_reopen_latest(rig, create, settings):
    client, repo, photos, provider = rig
    first = create()
    second = create()
    assert first["profiles"] == ["Older adult", "Baby", "Pet"]
    assert first["status"] == "ready" and first["attempts"] == 0
    assert len(provider.calls) == 0
    analyzed = client.post(base(second) + "/analyze").json()
    assert analyzed["status"] == "complete"
    assert analyzed["findings"][0]["status"] == "open"
    assert "not a professional home safety inspection" in analyzed["disclaimer"]
    assert "lease" not in analyzed and "input_hash" not in analyzed
    with TestClient(create_app(settings, repo, photos, provider)) as restarted:
        restarted.headers["X-Device-ID"] = client.headers["X-Device-ID"]
        assert restarted.get("/v1/assessments/latest").json() == analyzed
        assert restarted.get(base(first)).status_code == 200


def test_create_and_analysis_idempotency(rig, create, photo_bytes):
    client, _, photos, provider = rig
    aid = str(uuid4())
    one, two = create(assessment_id=aid), create(assessment_id=aid)
    assert one == two and len(photos.objects) == 1
    response = client.post(
        "/v1/assessments",
        data={"assessment_id": aid, "profiles": "[]"},
        files={"photo": ("x.png", photo_bytes)},
    )
    assert response.status_code == 409
    first = client.post(base(one) + "/analyze").json()
    second = client.post(base(one) + "/analyze").json()
    assert first == second and len(provider.calls) == 1


def test_failed_analysis_retains_photo_and_retries_once(rig, create, caplog):
    client, _, _, provider = rig
    provider.results.append(ModelError("upstream_http", upstream_status=429))
    assessment = create()
    response = client.post(base(assessment) + "/analyze")
    assert response.status_code == 502
    request_id = response.headers["X-Request-ID"]
    assert response.json()["error"]["request_id"] == request_id
    failed = client.get(base(assessment)).json()
    assert failed["status"] == "failed" and failed["attempts"] == 1
    assert failed["findings"] == [] and failed["summary"] is None
    assert client.get(base(assessment) + "/photos/" + failed["photo"]["id"]).status_code == 200
    assert "category=upstream_http" in caplog.text and request_id in caplog.text
    result = client.post(base(assessment) + "/analyze").json()
    assert result["id"] == assessment["id"] and result["attempts"] == 2
    assert len(result["findings"]) == 1 and len(provider.calls) == 2


def test_invalid_model_output_is_failure_not_empty_success(rig, create, caplog):
    client, _, _, provider = rig
    provider.results.append(
        {"summary": "Everything is safe", "findings": [{"credential": "secret-body"}]}
    )
    assessment = create()
    assert client.post(base(assessment) + "/analyze").status_code == 502
    assert client.get(base(assessment)).json()["status"] == "failed"
    assert "schema_validation" in caplog.text and "secret-body" not in caplog.text


def test_qualified_no_hazards_result(rig, create):
    client, _, _, provider = rig
    provider.results.append(
        {"summary": "No obvious visible hazards; this does not establish safety.", "findings": []}
    )
    assessment = create()
    result = client.post(base(assessment) + "/analyze").json()
    assert result["status"] == "complete" and result["findings"] == []
    assert result["summary"] and result["disclaimer"]


def test_failed_follow_up_preserves_finding_and_manual_retry(rig, assessed):
    client, _, _, provider = rig
    path = finding_path(assessed)
    patched = client.patch(path, json={"status": "dismissed", "note": "My decision"}).json()
    before = patched["findings"][0]
    sid = str(uuid4())
    submitted = client.post(
        path + "/submissions",
        data={
            "submission_id": sid,
            "kind": "follow-up",
            "text": "Yes, every night.",
        },
    )
    assert submitted.status_code == 201
    provider.results.append(ModelError("timeout"))
    analyze = path + f"/submissions/{sid}/analyze"
    assert client.post(analyze).status_code == 502
    failed = client.get(base(assessed)).json()["findings"][0]
    assert failed["evidence"] == before["evidence"] and failed["note"] == "My decision"
    assert failed["submissions"][0]["text"] == "Yes, every night."
    assert failed["submissions"][0]["status"] == "failed"
    provider.results.append(
        {"finding": {**content(), "severity": "High"}, "feedback": "The route is used at night."}
    )
    result = client.post(analyze).json()["findings"][0]
    assert result["status"] == "dismissed" and result["note"] == "My decision"
    assert result["severity"] == "High" and result["follow_up"]["state"] == "answered"
    assert len(result["submissions"]) == 1 and result["submissions"][0]["attempts"] == 2
    assert client.post(analyze).json()["findings"][0] == result
    assert len(provider.calls) == 3
    assert (
        client.post(
            path + "/submissions",
            data={
                "submission_id": str(uuid4()),
                "kind": "follow-up",
                "text": "Another answer",
            },
        ).status_code
        == 409
    )


def test_skip_then_user_reviews_remain_available(rig, assessed, photo_bytes):
    client, _, _, provider = rig
    path = finding_path(assessed)
    assert (
        client.post(path + "/skip-follow-up").json()["findings"][0]["follow_up"]["state"]
        == "skipped"
    )
    assert (
        client.post(
            path + "/submissions",
            data={
                "submission_id": str(uuid4()),
                "kind": "follow-up",
                "text": "Answer",
            },
        ).status_code
        == 409
    )
    assert (
        client.post(
            path + "/submissions",
            data={
                "submission_id": str(uuid4()),
                "kind": "review",
                "text": "Check it",
            },
        ).status_code
        == 422
    )
    client.patch(path, json={"status": "resolved"})
    for _ in range(2):
        sid = str(uuid4())
        response = client.post(
            path + "/submissions",
            data={"submission_id": sid, "kind": "review"},
            files={"photo": ("new.png", photo_bytes)},
        )
        assert response.status_code == 201
        provider.results.append(
            {"finding": content(), "feedback": "This photo cannot prove resolution."}
        )
        result = client.post(path + f"/submissions/{sid}/analyze").json()["findings"][0]
        assert result["status"] == "resolved" and result["follow_up"]["state"] == "skipped"
        assert len(provider.calls[-1]["images"]) == 2
    assert len(result["submissions"]) == 2
    assert client.patch(path, json={"status": "open"}).json()["findings"][0]["status"] == "open"


def test_photo_follow_up_requires_photo_and_same_id_is_idempotent(rig, create, photo_bytes):
    client, _, photos, provider = rig
    provider.results.append(assessment_result("photo"))
    assessment = create()
    result = client.post(base(assessment) + "/analyze").json()
    path = finding_path(result)
    sid = str(uuid4())
    data = {"submission_id": sid, "kind": "follow-up", "text": "Here"}
    assert client.post(path + "/submissions", data=data).status_code == 422
    for _ in range(2):
        response = client.post(
            path + "/submissions", data=data, files={"photo": ("x.png", photo_bytes)}
        )
        assert response.status_code == 201
        assert len(response.json()["findings"][0]["submissions"]) == 1
    assert len(photos.objects) == 2
    assert client.post(path + "/skip-follow-up").status_code == 409


def test_device_scoping_for_all_operations(rig, assessed, photo_bytes):
    client, _, _, _ = rig
    owner = client.headers["X-Device-ID"]
    client.headers["X-Device-ID"] = str(uuid4())
    path = finding_path(assessed)
    assert client.get(base(assessed)).status_code == 404
    assert client.get("/v1/assessments/latest").status_code == 404
    assert client.post(base(assessed) + "/analyze").status_code == 404
    assert client.get(base(assessed) + "/photos/" + assessed["photo"]["id"]).status_code == 404
    assert client.patch(path, json={"status": "resolved"}).status_code == 404
    assert client.post(path + "/skip-follow-up").status_code == 404
    assert (
        client.post(
            path + "/submissions",
            data={"submission_id": str(uuid4()), "kind": "review"},
            files={"photo": ("new.png", photo_bytes)},
        ).status_code
        == 404
    )
    assert client.delete(base(assessed)).status_code == 204
    client.headers["X-Device-ID"] = owner
    assert client.get(base(assessed)).status_code == 200


def test_partial_deletion_is_retryable_and_hidden(rig, create, assessed, photo_bytes):
    client, repo, photos, _ = rig
    previous = assessed
    newest = create()
    photos.fail_delete = True
    assert client.delete(base(newest)).status_code == 503
    assert client.get(base(newest)).status_code == 409
    assert client.post(base(newest) + "/analyze").status_code == 409
    assert client.get(base(newest) + "/photos/" + newest["photo"]["id"]).status_code == 409
    assert client.get("/v1/assessments/latest").json()["id"] == previous["id"]
    photos.fail_delete = False
    assert client.delete(base(newest)).status_code == 204
    assert client.delete(base(newest)).status_code == 204
    assert repo.get(client.headers["X-Device-ID"], newest["id"]) is None
    assert client.get(base(previous)).status_code == 200


def test_upload_failure_can_resend_same_id(rig, create, photo_bytes):
    client, _, photos, _ = rig
    aid = str(uuid4())
    photos.fail_upload = True
    response = client.post(
        "/v1/assessments", data={"assessment_id": aid}, files={"photo": ("room.png", photo_bytes)}
    )
    assert response.status_code == 503
    assert client.post(f"/v1/assessments/{aid}/analyze").status_code == 409
    photos.fail_upload = False
    saved = create(assessment_id=aid, profiles="[]")
    assert saved["photo"]["uploaded"] is True and len(photos.objects) == 1


def test_concurrent_analysis_and_deletion_cannot_overwrite_active_operation(rig, create):
    client, _, _, provider = rig
    assessment = create()

    def during_call():
        assert client.post(base(assessment) + "/analyze").status_code == 409
        assert client.delete(base(assessment)).status_code == 409

    provider.on_call = during_call
    assert client.post(base(assessment) + "/analyze").status_code == 200
    assert len(provider.calls) == 1


def test_interrupted_analysis_can_be_manually_retried_after_lease_expiry(rig, create):
    client, repo, _, provider = rig
    assessment = create()

    def interrupted(record):
        record.status = "running"
        record.attempts = 1
        record.lease = Lease(id=str(uuid4()), expires_at=now() - timedelta(seconds=1))
        return record

    repo.mutate(client.headers["X-Device-ID"], assessment["id"], interrupted)
    result = client.post(base(assessment) + "/analyze").json()
    assert result["status"] == "complete" and result["attempts"] == 2
    assert len(provider.calls) == 1


@pytest.mark.parametrize("bad_profiles", ['["Unknown"]', "{}", "broken", "[1]"])
def test_reject_invalid_input(rig, photo_bytes, bad_profiles):
    client, repo, photos, provider = rig
    response = client.post(
        "/v1/assessments",
        data={"assessment_id": str(uuid4()), "profiles": bad_profiles},
        files={"photo": ("room.png", photo_bytes)},
    )
    assert response.status_code == 422
    assert not repo.records and not photos.objects and not provider.calls


def test_auth_validation_and_unreadable_photo(rig, settings):
    client, repo, photos, provider = rig
    response = client.post(
        "/v1/assessments",
        data={"assessment_id": str(uuid4())},
        files={"photo": ("fake.jpg", b"not really a photo", "image/jpeg")},
    )
    assert response.status_code == 422
    assert not repo.records and not photos.objects
    client.headers["X-Device-ID"] = "../other-device"
    assert client.get("/v1/assessments/latest").status_code == 422
    from pydantic import SecretStr

    settings.demo_bearer_token = SecretStr("private-demo-token")
    assert client.get("/health").status_code == 401
    client.headers["Authorization"] = "Bearer private-demo-token"
    assert client.get("/health").status_code == 200


def test_status_changes_preserve_notes_unless_explicitly_cleared(rig, assessed):
    client, *_ = rig
    path = finding_path(assessed)
    client.patch(path, json={"status": "dismissed", "note": "Not relevant to this household"})
    reopened = client.patch(path, json={"status": "open"}).json()["findings"][0]
    assert reopened["note"] == "Not relevant to this household"
    cleared = client.patch(path, json={"status": "open", "note": ""}).json()["findings"][0]
    assert cleared["note"] == ""


def test_rejected_model_credentials_are_actionable_and_retained(rig, create):
    client, _, _, provider = rig
    provider.results.append(ModelError("upstream_http", upstream_status=401))
    assessment = create()
    response = client.post(base(assessment) + "/analyze")
    assert response.status_code == 502
    assert response.json()["error"]["code"] == "model_credentials_rejected"
    stored = client.get(base(assessment)).json()
    assert stored["status"] == "failed" and "API key" in stored["error"]


def test_unexpected_storage_errors_do_not_leak_exception_bodies(rig, caplog):
    client, repository, *_ = rig

    def fail(_):
        raise RuntimeError("private-api-key-and-image-data")

    repository.latest = fail
    response = client.get("/v1/assessments/latest")
    assert response.status_code == 503
    assert response.json()["error"]["request_id"] == response.headers["X-Request-ID"]
    assert "private-api-key-and-image-data" not in response.text + caplog.text


def test_provider_cannot_change_status_or_request_another_follow_up(rig, assessed, photo_bytes):
    client, _, _, provider = rig
    path = finding_path(assessed)
    sid = str(uuid4())
    assert (
        client.post(
            path + "/submissions",
            data={"submission_id": sid, "kind": "review"},
            files={"photo": ("x.png", photo_bytes)},
        ).status_code
        == 201
    )
    before = client.get(base(assessed)).json()["findings"][0]
    provider.results.append(
        {
            "finding": {
                **content(),
                "status": "resolved",
                "follow_up": {"kind": "photo", "question": "Again"},
            },
            "feedback": "Done",
        }
    )
    assert client.post(path + f"/submissions/{sid}/analyze").status_code == 502
    after = client.get(base(assessed)).json()["findings"][0]
    assert after["status"] == before["status"] and after["follow_up"] == before["follow_up"]
    assert after["submissions"][0]["status"] == "failed"
