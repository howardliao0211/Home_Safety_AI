from conftest import MemoryPhotos, MemoryRepository, StubProvider
from fastapi.testclient import TestClient

from app.main import create_app


def test_local_browser_preflight_and_error_responses_have_scoped_cors(settings):
    with TestClient(
        create_app(settings, MemoryRepository(), MemoryPhotos(), StubProvider())
    ) as client:
        headers = {
            "Origin": "http://localhost:8081",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "authorization,x-deletion-receipt,content-type",
        }
        response = client.options("/v1/assessments", headers=headers)
        assert response.status_code == 200
        assert response.headers["Access-Control-Allow-Origin"] == "http://localhost:8081"
        response = client.get("/v1/assessments/latest", headers={"Origin": "http://localhost:8081"})
        assert response.status_code == 401
        assert response.headers["Access-Control-Allow-Origin"] == "http://localhost:8081"
        response = client.options(
            "/v1/assessments", headers={**headers, "Origin": "https://untrusted.example"}
        )
        assert response.status_code == 400
        assert "Access-Control-Allow-Origin" not in response.headers
