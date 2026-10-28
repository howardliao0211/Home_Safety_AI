import os
from uuid import uuid4

import pytest
from conftest import StubProvider
from fastapi.testclient import TestClient
from test_annotations import HighlightProvider

from app.config import Settings
from app.main import create_app
from app.models.schemas import Photo

pytestmark = [
    pytest.mark.emulator,
    pytest.mark.skipif(
        os.getenv("RUN_EMULATOR_TESTS") != "1", reason="Requires local storage emulators"
    ),
]


def test_queued_highlight_survives_api_restart_local_worker_and_asset_deletion(
    photo_bytes, monkeypatch
):
    monkeypatch.setenv("FIRESTORE_EMULATOR_HOST", "127.0.0.1:8080")
    config = Settings(_env_file=None, groq_api_key="test", groq_model="test")
    device, aid = str(uuid4()), str(uuid4())
    safety, highlighting = StubProvider(), HighlightProvider()
    base = f"/v1/assessments/{aid}"
    with TestClient(create_app(config, provider=safety, highlight_provider=highlighting)) as client:
        client.headers["X-Device-ID"] = device
        assert (
            client.post(
                "/v1/assessments",
                data={"assessment_id": aid},
                files={"photo": ("room.png", photo_bytes)},
            ).status_code
            == 201
        )
        a = client.post(base + "/analyze").json()
        annotations = base + f"/findings/{a['findings'][0]['id']}/annotations"
        job = a["findings"][0]["annotation"]
        assert job["state"] == "queued" and highlighting.calls == []
    with TestClient(
        create_app(config, provider=StubProvider(), highlight_provider=highlighting)
    ) as client:
        client.headers["X-Device-ID"] = device
        service = client.app.state.annotations
        try:
            assert any(a.id == aid for a in service.repository.annotation_pending())
            service.recover()
            ready = client.get(annotations + "/" + job["id"]).json()
            assert ready["state"] == "ready"
            assert client.get(annotations + "/" + job["id"] + "/mask").status_code == 200
            service.work(device, aid, job["id"])
            assert highlighting.calls == ["black power cable"]
            assert client.delete(base).status_code == 204
            assert not any(asset[1] == aid for asset in service.photos.annotation_assets())
            # A worker crash immediately after a deletion-racing upload must also
            # be recoverable after its parent record has already disappeared.
            orphan = Photo(
                id="annotation-" + str(uuid4()), content_type="image/png", sha256="unused"
            )
            service.photos.put(device, aid, orphan, b"orphan")
            service.reap_assets()
            assert not any(asset[1] == aid for asset in service.photos.annotation_assets())
        finally:
            client.delete(base)
