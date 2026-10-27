"""Local browser-integration server: real HTTP/storage, deterministic test model.

This file is excluded from the production Docker build. Never deploy this entrypoint.
"""

import uvicorn
from pydantic import BaseModel

from app.config import Settings
from app.errors import ModelError
from app.main import create_app
from app.models.schemas import FindingContent


class IntegrationProvider:
    name = "integration-fixture"
    model = "deterministic-browser-test"

    def __init__(self):
        self.fail_initial = 0
        self.fail_revision = 0

    def generate(self, *, system: str, context: dict, images: list, schema: type[BaseModel]):
        if schema.__name__ == "AssessmentResult":
            if self.fail_initial:
                self.fail_initial -= 1
                raise ModelError("upstream_http", upstream_status=429)
            common = {
                "category": "Trips & falls",
                "severity": "Medium",
                "evidence": "A cable is visible across the walking route.",
                "recommendation": "If safe, keep the walking route clear.",
                "short_action": "Keep the route clear.",
                "uncertainty": "The photo cannot establish how often the route is used.",
            }
            return {
                "summary": "Browser integration fixture: two potential findings.",
                "findings": [
                    {
                        **common,
                        "title": "Keep the walkway clear",
                        "follow_up": {"kind": "text", "question": "Is this route used at night?"},
                    },
                    {
                        **common,
                        "title": "Check the cabinet",
                        "severity": "High",
                        "category": "Furniture",
                        "follow_up": {
                            "kind": "photo",
                            "question": "Can you safely show the cabinet's wall attachment?",
                        },
                    },
                ],
            }
        if self.fail_revision:
            self.fail_revision -= 1
            raise ModelError("timeout")
        finding = {key: context["finding"][key] for key in FindingContent.model_fields}
        finding["evidence"] = "Additional evidence was considered in this linked check."
        return {
            "finding": finding,
            "feedback": "New evidence adds context; you decide whether to resolve this finding.",
        }

    def close(self):
        pass


provider = IntegrationProvider()
settings = Settings(
    _env_file=None,
    environment="local",
    groq_api_key="unused-fixture-key",
    groq_model="unused-fixture-model",
    google_cloud_project="home-safety-local",
    photos_bucket="home-safety-local-photos",
    firestore_emulator_host="127.0.0.1:8080",
    storage_emulator_host="http://127.0.0.1:4443",
    demo_bearer_token="browser-integration-token",
    cors_origins=["http://127.0.0.1:8082", "http://localhost:8082"],
)
app = create_app(settings, provider=provider)


@app.get("/__test/ready")
def ready():
    return {"fixture": True}


@app.post("/__test/control")
def control(configuration: dict):
    provider.fail_initial = int(configuration.get("fail_initial", 0))
    provider.fail_revision = int(configuration.get("fail_revision", 0))
    return {"configured": True}


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8001)
