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
        if config.demo_bearer_token:
            client.headers["Authorization"] = (
                f"Bearer {config.demo_bearer_token.get_secret_value()}"
            )
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
