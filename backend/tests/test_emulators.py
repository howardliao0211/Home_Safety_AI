import os
import time
from uuid import uuid4

import pytest
from conftest import StubProvider, content
from fastapi.testclient import TestClient

from app.config import ROOT, Settings
from app.main import create_app
from app.models.providers.factory import build_provider
from app.models.schemas import new_id
from app.storage.photos import GCSPhotoStore
from app.storage.repository import FirestoreRepository

pytestmark = [
    pytest.mark.emulator,
    pytest.mark.skipif(
        os.getenv("RUN_EMULATOR_TESTS") != "1",
        reason="Set RUN_EMULATOR_TESTS=1 with local storage services running.",
    ),
]


def test_cloud_adapters_roundtrip_restart_and_delete(photo_bytes, monkeypatch):
    monkeypatch.setenv("FIRESTORE_EMULATOR_HOST", "127.0.0.1:8080")
    config = Settings(
        _env_file=None,
        groq_api_key="unused-test-key",
        groq_model="unused-model",
        firestore_emulator_host="127.0.0.1:8080",
        storage_emulator_host="http://127.0.0.1:4443",
    )
    device, aid, sid = str(uuid4()), new_id(), new_id()
    provider = StubProvider()
    with TestClient(create_app(config, provider=provider)) as client:
        client.headers["X-Device-ID"] = device
        client.headers["Authorization"] = "Bearer " + device
        path = f"/v1/assessments/{aid}"
        try:
            response = client.post(
                "/v1/assessments",
                data={"assessment_id": aid, "profiles": '["Pet"]'},
                files={"photo": ("room.png", photo_bytes)},
            )
            assert response.status_code == 201, response.text
            saved = response.json()
            result = client.post(path + "/analyze")
            assert result.status_code == 200, result.text
            fid = result.json()["findings"][0]["id"]
            finding_path = path + f"/findings/{fid}"
            response = client.post(
                finding_path + "/submissions",
                data={"submission_id": sid, "kind": "review"},
                files={"photo": ("new.png", photo_bytes)},
            )
            assert response.status_code == 201, response.text
            provider.results.append(
                {"finding": content(), "feedback": "Review complete with uncertainty."}
            )
            response = client.post(finding_path + f"/submissions/{sid}/analyze")
            assert response.status_code == 200, response.text
            response = client.patch(
                finding_path, json={"status": "resolved", "note": "Reviewed by me"}
            )
            expected = response.json()
            # Fresh SDK clients model a process restart rather than retained Python state.
            repository, photos = FirestoreRepository(config), GCSPhotoStore(config)
            try:
                reopened = repository.latest(device)
                assert reopened.id == aid and reopened.findings[0].status == "resolved"
                assert (
                    reopened.findings[0].submissions[0].feedback
                    == "Review complete with uncertainty."
                )
                assert photos.get(device, aid, reopened.photo).startswith(b"\xff\xd8")
            finally:
                repository.close()
                photos.close()
            assert client.get(path).json() == expected
            assert client.get(path + "/photos/" + saved["photo"]["id"]).status_code == 200
            assert client.delete(path).status_code == 204
            assert client.get(path).status_code == 404
            assert (
                list(
                    client.app.state.service.photos.client.list_blobs(
                        config.photos_bucket, prefix=f"devices/{device}/assessments/{aid}/"
                    )
                )
                == []
            )
        finally:
            client.delete(path)


@pytest.mark.live
@pytest.mark.skipif(
    os.getenv("RUN_LIVE_MODEL_TESTS") != "1", reason="Opt in to a real paid model call."
)
def test_real_model_photo_assessment_and_review(monkeypatch):
    monkeypatch.setenv("FIRESTORE_EMULATOR_HOST", "127.0.0.1:8080")
    config = Settings()
    assert config.environment == "local", "Live smoke test must use local storage"
    device, aid = new_id(), new_id()
    provider = build_provider(config)
    with TestClient(create_app(config, provider=provider)) as client:
        client.headers["X-Device-ID"] = device
        client.headers["Authorization"] = "Bearer " + device
        path = f"/v1/assessments/{aid}"
        try:
            with (ROOT / "mobile/assets/rooms/living-room.jpg").open("rb") as image:
                response = client.post(
                    "/v1/assessments",
                    data={"assessment_id": aid, "profiles": '["Baby", "Pet"]'},
                    files={"photo": ("room.jpg", image, "image/jpeg")},
                )
            assert response.status_code == 201, response.text
            response = client.post(path + "/analyze")
            assert response.status_code == 200, response.text
            assessment = response.json()
            assert (
                assessment["status"] == "complete"
                and assessment["provider"] == config.model_provider
            )
            # This verifies the integration, not detection accuracy on a single scene.
            if assessment["findings"]:
                # Explicit smoke-test pacing for small development quotas. The
                # application/provider never sleeps or retries a failed model call.
                interval = min(60, max(0, float(os.getenv("LIVE_MODEL_INTERVAL_SECONDS", "0"))))
                time.sleep(interval)
                fid, sid = assessment["findings"][0]["id"], new_id()
                finding_path = path + f"/findings/{fid}"
                with (ROOT / "mobile/assets/rooms/living-room.jpg").open("rb") as image:
                    response = client.post(
                        finding_path + "/submissions",
                        data={"submission_id": sid, "kind": "review"},
                        files={"photo": ("review.jpg", image, "image/jpeg")},
                    )
                assert response.status_code == 201, response.text
                response = client.post(finding_path + f"/submissions/{sid}/analyze")
                assert response.status_code == 200, response.text
                finding = response.json()["findings"][0]
                assert finding["status"] == "open" and finding["submissions"][0]["feedback"]
        finally:
            client.delete(path)


def test_finding_chat_jobs_survive_restart_stream_partials_and_delete(photo_bytes, monkeypatch):
    import threading

    from conftest import Script

    monkeypatch.setenv("FIRESTORE_EMULATOR_HOST", "127.0.0.1:8080")
    config = Settings(
        _env_file=None,
        groq_api_key="unused",
        groq_model="unused",
        firestore_emulator_host="127.0.0.1:8080",
        storage_emulator_host="http://127.0.0.1:4443",
    )
    uid, aid, tid = new_id(), new_id(), new_id()
    base = f"/v1/assessments/{aid}"
    with TestClient(create_app(config, provider=StubProvider())) as client:
        client.headers["Authorization"] = "Bearer " + uid
        try:
            created = client.post(
                "/v1/assessments",
                data={"assessment_id": aid},
                files={"photo": ("room.png", photo_bytes)},
            )
            assert created.status_code == 201
            fid = client.post(base + "/analyze").json()["findings"][0]["id"]
            path = base + f"/findings/{fid}/chat"
            question = {"id": tid, "question": "What can I do about the cable?"}
            accepted = client.post(path + "/turns", json=question)
            assert accepted.status_code == 201, accepted.text
            assert accepted.json()["turns"][0]["status"] == "queued"
        except Exception:
            client.delete(base)
            raise
    # A separate worker process (fresh app and SDK clients) finds the saved job
    # through the Firestore recovery index and streams it.
    worker_provider = StubProvider()
    first_out, release = threading.Event(), threading.Event()

    def pause():
        first_out.set()
        assert release.wait(10)

    worker_provider.results.append(Script(["Keep the route ", "clear if safe."], gates={1: pause}))
    with (
        TestClient(create_app(config, provider=worker_provider)) as worker,
        TestClient(create_app(config, provider=StubProvider())) as installation,
    ):
        installation.headers["Authorization"] = "Bearer " + uid
        try:
            chat = worker.app.state.chat
            items = [item for item in chat.pending() if item[1] == aid]
            assert len(items) == 1
            thread = threading.Thread(target=chat.work, args=items[0])
            thread.start()
            assert first_out.wait(10)
            during = installation.get(path).json()["turns"][0]
            assert during["status"] == "running" and during["partial"] == "Keep the route "
            release.set()
            thread.join(10)
            done = installation.get(path).json()["turns"][0]
            assert done["status"] == "complete"
            assert done["answer"] == "Keep the route clear if safe."
            chat.work(*items[0])  # Redelivery after restart never re-runs the model.
            assert len(worker_provider.calls) == 1
            # A job running when the assessment is deleted cannot resurrect it.
            second = {"id": new_id(), "question": "And at night?"}
            assert installation.post(path + "/turns", json=second).status_code == 201
            (item,) = [i for i in chat.pending() if i[1] == aid]

            def delete():
                assert installation.delete(base).status_code == 204

            worker_provider.results.append(Script(["Late ", "write."], gates={1: delete}))
            chat.work(*item)
            assert installation.get(path).status_code == 404
            repo = FirestoreRepository(config)
            try:
                assert repo.get(uid, aid) is None
            finally:
                repo.close()
        finally:
            installation.delete(base)
