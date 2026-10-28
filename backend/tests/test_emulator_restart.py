import os
import subprocess
import time
from uuid import uuid4

import httpx
import pytest
from conftest import StubProvider
from fastapi.testclient import TestClient

from app.config import ROOT, Settings
from app.main import create_app


@pytest.mark.emulator
@pytest.mark.skipif(
    os.getenv("RUN_EMULATOR_RESTART_TESTS") != "1",
    reason="Opt in to a check that stops and restarts the local storage services.",
)
def test_data_survives_emulator_restart(photo_bytes, monkeypatch):
    monkeypatch.setenv("FIRESTORE_EMULATOR_HOST", "127.0.0.1:8080")
    settings = Settings(_env_file=None, groq_api_key="unused", groq_model="unused")
    device, aid = str(uuid4()), str(uuid4())
    path = f"/v1/assessments/{aid}"
    with TestClient(create_app(settings, provider=StubProvider())) as client:
        client.headers["X-Device-ID"] = device
        client.headers["Authorization"] = "Bearer " + device
        response = client.post(
            "/v1/assessments",
            data={"assessment_id": aid},
            files={"photo": ("room.png", photo_bytes)},
        )
        assert response.status_code == 201, response.text
        response = client.post(path + "/analyze")
        assert response.status_code == 200, response.text
        saved = response.json()
    compose = ["docker", "compose", "-f", str(ROOT / "backend/compose.yaml")]
    subprocess.run([*compose, "stop"], check=True, timeout=60, capture_output=True)
    subprocess.run([*compose, "start"], check=True, timeout=30, capture_output=True)
    for _ in range(100):
        try:
            httpx.get("http://127.0.0.1:8080/", timeout=1)
            httpx.get("http://127.0.0.1:4443/storage/v1/b", timeout=1)
            break
        except httpx.TransportError:
            time.sleep(0.2)
    else:
        pytest.fail("Local storage services did not restart")
    with TestClient(create_app(settings, provider=StubProvider())) as client:
        client.headers["X-Device-ID"] = device
        client.headers["Authorization"] = "Bearer " + device
        try:
            response = client.get(path)
            assert response.status_code == 200, response.text
            assert response.json() == saved
            assert client.get(path + "/photos/" + saved["photo"]["id"]).status_code == 200
        finally:
            assert client.delete(path).status_code == 204
