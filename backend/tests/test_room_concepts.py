from datetime import timedelta
from uuid import uuid4

import pytest

from app.models.schemas import now


class Images:
    model = "image-model"

    def __init__(self, data):
        self.calls = []
        self.data = data
        self.error = None
        self.on_call = None

    def generate(self, prompt, photo, content_type, *, deadline):
        self.calls.append((prompt, photo))
        if self.on_call:
            self.on_call()
        if self.error:
            raise self.error
        return self.data, 100, 60


@pytest.fixture
def images(rig, photo_bytes):
    client, *_ = rig
    provider = Images(photo_bytes)
    client.app.state.room_concepts.provider = provider
    return provider


def run_job(rig, aid):
    client, records, *_ = rig
    owner = client.headers["X-Device-ID"]
    job = records.get(owner, aid).room_concept
    client.app.state.room_concepts.work(owner, aid, job.attempt_id)


def test_automatic_once_saved_private_image(rig, images, assessed):
    client, records, *_ = rig
    aid = assessed["id"]
    assert assessed["room_concept"]["state"] == "queued"
    assert images.calls == []  # Initial analysis never waits for generation.
    assert "prompt" not in assessed["room_concept"]
    run_job(rig, aid)
    run_job(rig, aid)
    state = client.get(f"/v1/assessments/{aid}/room-concept").json()
    assert state["state"] == "ready"
    assert len(images.calls) == 1
    image = client.get(f"/v1/assessments/{aid}/room-concept/image")
    assert image.status_code == 200
    assert image.headers["cache-control"] == "no-store"
    original = assessed["findings"]
    assert client.get(f"/v1/assessments/{aid}").json()["findings"] == original
    client.post(f"/v1/assessments/{aid}/room-concept/retry", json={"attempt_id": str(uuid4())})
    run_job(rig, aid)
    assert len(images.calls) == 1


def test_failure_manual_retry_uses_frozen_initial_input(rig, images, assessed):
    client, *_ = rig
    aid, fid = assessed["id"], assessed["findings"][0]["id"]
    images.error = RuntimeError("private provider payload")
    run_job(rig, aid)
    assert client.get(f"/v1/assessments/{aid}/room-concept").json()["state"] == "failed"
    client.patch(f"/v1/assessments/{aid}/findings/{fid}", json={"status": "dismissed"})
    images.error = None
    attempt = {"attempt_id": str(uuid4())}
    client.post(f"/v1/assessments/{aid}/room-concept/retry", json=attempt)
    client.post(f"/v1/assessments/{aid}/room-concept/retry", json=attempt)
    run_job(rig, aid)
    assert len(images.calls) == 2
    assert images.calls[0] == images.calls[1]


def test_no_findings_or_legacy_read_never_generates(rig, images, create):
    client, records, _, provider = rig
    provider.results.append({"suggestions": [], "findings": []})
    aid = create()["id"]
    result = client.post(f"/v1/assessments/{aid}/analyze").json()
    assert result["room_concept"]["state"] == "not_applicable"
    assert images.calls == []
    owner = client.headers["X-Device-ID"]

    def legacy(a):
        a.room_concept = None
        return a

    records.mutate(owner, aid, legacy)
    assert client.get(f"/v1/assessments/{aid}").json()["room_concept"] is None
    assert client.get(f"/v1/assessments/{aid}/room-concept").status_code == 404


def test_expired_attempt_never_restarts(rig, images, assessed):
    client, records, *_ = rig
    owner, aid = client.headers["X-Device-ID"], assessed["id"]

    def expired(a):
        a.room_concept.queued_until = now() - timedelta(seconds=1)
        return a

    records.mutate(owner, aid, expired)
    run_job(rig, aid)
    assert not images.calls
    assert client.get(f"/v1/assessments/{aid}/room-concept").json()["state"] == "failed"


def test_deletion_wins_during_generation(rig, images, assessed):
    client, _, photos, _ = rig
    aid = assessed["id"]
    images.on_call = lambda: client.delete(f"/v1/assessments/{aid}")
    run_job(rig, aid)
    assert client.get(f"/v1/assessments/{aid}").status_code == 404
    assert not photos.objects


def test_other_account_cannot_read_retry_or_fetch(rig, images, assessed):
    client, *_ = rig
    aid = assessed["id"]
    run_job(rig, aid)
    client.headers["Authorization"] = "Bearer " + str(uuid4())
    assert client.get(f"/v1/assessments/{aid}/room-concept").status_code == 404
    assert client.get(f"/v1/assessments/{aid}/room-concept/image").status_code == 404
    assert (
        client.post(
            f"/v1/assessments/{aid}/room-concept/retry", json={"attempt_id": str(uuid4())}
        ).status_code
        == 404
    )


def test_simultaneous_delivery_claims_once(rig, images, assessed):
    import threading
    from concurrent.futures import ThreadPoolExecutor

    started, release = threading.Event(), threading.Event()

    def pause():
        started.set()
        assert release.wait(5)

    images.on_call = pause
    with ThreadPoolExecutor(2) as workers:
        first = workers.submit(run_job, rig, assessed["id"])
        assert started.wait(5)
        duplicate = workers.submit(run_job, rig, assessed["id"])
        duplicate.result(5)
        release.set()
        first.result(5)
    assert len(images.calls) == 1


def test_dispatch_failure_recovers_unstarted_job(rig, images, create):
    client, *_ = rig

    class Dispatch:
        calls = []
        broken = True

        def enqueue_room_concept(self, *args):
            self.calls.append(args)
            if self.broken:
                raise OSError("queue unavailable")

    dispatch = Dispatch()
    service = client.app.state.room_concepts
    service.dispatcher = dispatch
    aid = create()["id"]
    assert client.post(f"/v1/assessments/{aid}/analyze").status_code == 200
    assert len(dispatch.calls) == 1
    dispatch.broken = False
    service.recover()
    assert len(dispatch.calls) == 2
    assert dispatch.calls[0] == dispatch.calls[1]
    assert not images.calls
    run_job(rig, aid)
    service.recover()
    assert len(dispatch.calls) == 2


def test_upload_after_deletion_is_removed(rig, images, assessed, monkeypatch):
    client, _, photos, _ = rig
    aid = assessed["id"]
    put = photos.put

    def late_upload(owner, aid, photo, data, **kwargs):
        client.delete(f"/v1/assessments/{aid}")
        put(owner, aid, photo, data, **kwargs)

    monkeypatch.setattr(photos, "put", late_upload)
    run_job(rig, aid)
    assert not photos.objects


def test_orphans_reaped_but_ready_image_retained(rig, images, assessed):
    client, _, photos, _ = rig
    run_job(rig, assessed["id"])
    photos.objects[(client.headers["X-Device-ID"], str(uuid4()), "room-concept-orphan")] = b"orphan"
    client.app.state.room_concepts.reap_assets()
    assert all(key[2] != "room-concept-orphan" for key in photos.objects)
    assert client.get(f"/v1/assessments/{assessed['id']}/room-concept/image").status_code == 200


def test_unconfigured_feature_does_not_fail_assessment(rig, assessed):
    assert assessed["room_concept"]["state"] == "unavailable"
    assert assessed["status"] == "complete"


def test_storage_failure_preserves_findings_and_allows_retry(rig, images, assessed):
    client, _, photos, _ = rig
    photos.fail_upload = True
    run_job(rig, assessed["id"])
    saved = client.get(f"/v1/assessments/{assessed['id']}").json()
    assert saved["status"] == "complete"
    assert saved["findings"] == assessed["findings"]
    assert saved["room_concept"]["can_retry"] is True


def test_late_firestore_commit_cannot_publish_ready_concept(
    rig, images, assessed, settings, monkeypatch
):
    import time
    from types import SimpleNamespace
    from unittest.mock import MagicMock

    from google.cloud import firestore

    from app.storage.repository import FirestoreRepository

    client, memory, *_ = rig
    owner, aid = client.headers["X-Device-ID"], assessed["id"]
    saved = memory.get(owner, aid)
    saved.room_concept.state = "running"
    saved.room_concept.expires_at = now() + timedelta(seconds=1)
    cloud = MagicMock()
    cloud.collection.return_value.document.return_value.get.return_value.to_dict.return_value = None
    snapshot = cloud.collection.return_value.document.return_value.collection.return_value.document.return_value.get.return_value
    snapshot.exists = True
    snapshot.to_dict.return_value = saved.model_dump(mode="python")
    cloud._firestore_api.commit.return_value.write_results = [
        SimpleNamespace(update_time=now() + timedelta(seconds=2))
    ]
    monkeypatch.setattr("app.storage.repository.firestore.Client", lambda **kwargs: cloud)
    records = FirestoreRepository(settings)

    def publish(a):
        a.room_concept.state = "ready"
        a.room_concept.finished_at = now()
        return a

    result = records.mutate(owner, aid, publish, deadline=time.monotonic() + 10)
    assert result.room_concept.state == "failed"
    assert result.room_concept.error_code == "publication_timeout"
    payload = cloud.transaction.return_value.update.call_args.args[1]
    assert payload["room_concept_commit"] is firestore.SERVER_TIMESTAMP


def test_large_optional_snapshot_never_fails_initial_assessment(rig, images, create):
    from conftest import assessment_result

    client, _, _, safety = rig
    result = assessment_result()
    finding = result["findings"][0]
    for key in ("evidence", "recommendation", "uncertainty"):
        finding[key] = "安" * 3000
    result["findings"] = [finding.copy() for _ in range(12)]
    safety.results.append(result)
    aid = create()["id"]
    response = client.post(f"/v1/assessments/{aid}/analyze")
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "complete"
    assert response.json()["room_concept"]["state"] == "unavailable"
    assert not images.calls


def test_failure_diagnostics_are_specific_and_do_not_log_payloads(rig, images, assessed, caplog):
    from app.errors import ModelError

    images.error = ModelError("credentials_rejected", upstream_status=403)
    run_job(rig, assessed["id"])
    assert "category=credentials_rejected" in caplog.text
    assert "upstream_status=403" in caplog.text
    assert "request_id=" in caplog.text and "frames=" in caplog.text
    assert "data:image" not in caplog.text
