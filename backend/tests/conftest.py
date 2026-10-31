import copy
import io
import threading
from collections import deque
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.config import Settings
from app.main import create_app
from app.models.schemas import Assessment
from app.storage.repository import check_size


class StubIdentity:
    """External managed identity boundary; real SDK covered by emulator tests."""

    def __init__(self, settings=None):
        pass

    def verify(self, token):
        from uuid import UUID

        from app.errors import AppError

        try:
            UUID(token)
        except ValueError:
            raise AppError(401, "unauthorized", "Sign in again.") from None
        return {"uid": token, "email_verified": True, "auth_time": 0}

    def close(self):
        pass


@pytest.fixture(autouse=True)
def managed_identity_boundary(monkeypatch):
    monkeypatch.setattr("app.main.FirebaseIdentity", StubIdentity)


class MemoryRepository:
    def __init__(self):
        self.records = {}
        self.lock = threading.Lock()

    def get(self, device_id, assessment_id):
        with self.lock:
            return copy.deepcopy(self.records.get((device_id, assessment_id)))

    def latest(self, device_id):
        with self.lock:
            records = [
                a
                for (device, _), a in self.records.items()
                if device == device_id and not a.deleting
            ]
            return copy.deepcopy(max(records, key=lambda a: a.created_at)) if records else None

    def mutate(self, device_id, assessment_id, change, *, deadline=None):
        with self.lock:
            key = (device_id, assessment_id)
            updated = change(copy.deepcopy(self.records.get(key)))
            if updated is None:
                self.records.pop(key, None)
            else:
                check_size(updated)
                # Enforce the same serialization boundary as Firestore.
                self.records[key] = Assessment.model_validate_json(updated.model_dump_json())
            return copy.deepcopy(updated)

    def history(self, owner_uid, limit, after=None):
        with self.lock:
            records = sorted(
                (
                    a
                    for (owner, _), a in self.records.items()
                    if owner == owner_uid and not a.deleting
                ),
                key=lambda a: (a.created_at, a.id),
                reverse=True,
            )
            if after:
                records = [a for a in records if (a.created_at, a.id) < after]
            return copy.deepcopy(records[:limit])

    def annotation_pending(self):
        return [copy.deepcopy(a) for a in self.records.values() if a.annotation_dispatch_pending]

    def chat_pending(self):
        return [copy.deepcopy(a) for a in self.records.values() if a.chat_dispatch_pending]

    def close(self):
        pass


class MemoryPhotos:
    def __init__(self):
        self.objects = {}
        self.fail_delete = False
        self.fail_upload = False

    def put(self, device_id, assessment_id, photo, data, *, timeout=20):
        if self.fail_upload:
            raise OSError("test upload failure")
        self.objects[(device_id, assessment_id, photo.id)] = data

    def get(self, device_id, assessment_id, photo, *, timeout=20):
        return self.objects[(device_id, assessment_id, photo.id)]

    def delete(self, device_id, assessment_id, photo):
        self.objects.pop((device_id, assessment_id, photo.id), None)

    def delete_assessment(self, device_id, assessment_id):
        for key in list(self.objects):
            if key[:2] == (device_id, assessment_id):
                del self.objects[key]
                if self.fail_delete:
                    raise OSError("test partial deletion")

    def annotation_assets(self):
        return [
            (device, aid, key.removeprefix("annotation-"))
            for device, aid, key in list(self.objects)
            if key.startswith("annotation-")
        ]

    def close(self):
        pass


def content():
    return {
        "title": "Loose cable across the walkway",
        "category": "Trips & falls",
        "severity": "Medium",
        "evidence": "A loose cable crosses the visible walkway.",
        "recommendation": "If safe, keep the cable away from the walking route.",
        "short_action": "Keep the walking route clear.",
        "uncertainty": "The image does not establish how often this route is used.",
    }


def assessment_result(follow_up_kind="text"):
    return {
        "suggestions": [
            "Start with the cable across the walking route.",
            "Keep the route clear, especially at night.",
            "Check again after moving furniture.",
        ],
        "findings": [
            {
                **content(),
                "follow_up": {"kind": follow_up_kind, "question": "Is this route used at night?"},
                "segmentation_prompt": "black power cable",
            }
        ],
    }


class StubProvider:
    name = "test"
    model = "test-vision"

    def __init__(self):
        self.results = deque()
        self.calls = []
        self.on_call = None

    def generate(self, **kwargs):
        self.calls.append(kwargs)
        if self.on_call:
            self.on_call()
        result = self.results.popleft() if self.results else assessment_result()
        if isinstance(result, Exception):
            raise result
        return copy.deepcopy(result)

    def stream_text(self, **kwargs):
        """Chat streaming: a queued {"answer"} is split into fragments; a Script
        controls fragments, pauses and a failure after partial output."""
        self.calls.append(kwargs)
        if self.on_call:
            self.on_call()
        result = self.results.popleft() if self.results else {"answer": "A short reply."}
        if isinstance(result, Exception):
            raise result
        if isinstance(result, dict):
            answer = result["answer"]
            half = len(answer) // 2
            result = Script([answer[:half], answer[half:]])
        return result.run()

    def close(self):
        pass


class Script:
    """Deterministic provider stream: fragments, optional gates, optional error."""

    def __init__(self, fragments, error=None, gates=None):
        self.fragments, self.error, self.gates = fragments, error, gates or {}

    def run(self):
        for index, fragment in enumerate(self.fragments):
            gate = self.gates.get(index)
            if gate:
                gate()
            yield fragment
        if self.error:
            raise self.error


@pytest.fixture
def photo_bytes():
    image = Image.new("RGB", (100, 60), (210, 180, 160))
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


@pytest.fixture
def settings():
    return Settings(_env_file=None, groq_api_key="test-key", groq_model="test-model")


@pytest.fixture
def rig(settings):
    repository, photos, provider = MemoryRepository(), MemoryPhotos(), StubProvider()
    app = create_app(settings, repository, photos, provider)
    with TestClient(app) as client:
        client.headers["X-Device-ID"] = str(uuid4())
        client.headers["Authorization"] = "Bearer " + client.headers["X-Device-ID"]
        yield client, repository, photos, provider


@pytest.fixture
def create(rig, photo_bytes):
    client, *_ = rig

    def run(**overrides):
        response = client.post(
            "/v1/assessments",
            data={
                "assessment_id": str(uuid4()),
                "profiles": '["Older adult", "Baby", "Pet"]',
                **overrides,
            },
            files={"photo": ("room.png", photo_bytes, "image/png")},
        )
        assert response.status_code == 201, response.text
        return response.json()

    return run


@pytest.fixture
def assessed(rig, create):
    client, *_ = rig
    assessment = create()
    response = client.post(f"/v1/assessments/{assessment['id']}/analyze")
    assert response.status_code == 200, response.text
    return response.json()
