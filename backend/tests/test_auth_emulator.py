"""Real Firebase Admin verification against the Auth and storage emulators."""

import base64
import json
import os
import time
from uuid import uuid4

import httpx
import pytest
from conftest import StubProvider
from fastapi.testclient import TestClient
from firebase_admin import auth

from app.auth import FirebaseIdentity
from app.config import Settings
from app.main import create_app

pytestmark = [
    pytest.mark.emulator,
    pytest.mark.skipif(
        os.getenv("RUN_EMULATOR_TESTS") != "1", reason="Requires Auth/Firestore/GCS emulators"
    ),
]


def test_managed_accounts_verification_ownership_revocation_and_deletion(photo_bytes, monkeypatch):
    monkeypatch.setenv("FIREBASE_AUTH_EMULATOR_HOST", "127.0.0.1:9099")
    monkeypatch.setenv("FIRESTORE_EMULATOR_HOST", "127.0.0.1:8080")
    config = Settings(
        _env_file=None,
        groq_api_key="test",
        groq_model="test",
        firebase_auth_emulator_host="127.0.0.1:9099",
    )
    identity = FirebaseIdentity(config)
    emails = [f"{uuid4()}@example.test" for _ in range(2)]
    endpoint = "http://127.0.0.1:9099/identitytoolkit.googleapis.com/v1/accounts:"
    users = []
    for email in emails:
        result = httpx.post(
            endpoint + "signUp?key=local",
            json={"email": email, "password": "A-strong-password-123", "returnSecureToken": True},
        ).json()
        assert "idToken" in result, result
        users.append(result)
    with TestClient(create_app(config, provider=StubProvider(), identity=identity)) as client:
        client.headers["Authorization"] = "Bearer " + users[0]["idToken"]
        assert client.get("/v1/assessments/latest").status_code == 403
        for index, user in enumerate(users):
            auth.update_user(user["localId"], email_verified=True, app=identity.app)
            users[index] = httpx.post(
                endpoint + "signInWithPassword?key=local",
                json={
                    "email": emails[index],
                    "password": "A-strong-password-123",
                    "returnSecureToken": True,
                },
            ).json()
        client.headers["Authorization"] = "Bearer " + users[0]["idToken"]
        aid = str(uuid4())
        response = client.post(
            "/v1/assessments",
            data={"assessment_id": aid},
            files={"photo": ("room.png", photo_bytes)},
        )
        assert response.status_code == 201, response.text
        photo = response.json()["photo"]["id"]
        path = "/v1/assessments/" + aid
        client.headers["Authorization"] = "Bearer " + users[1]["idToken"]
        assert client.get(path).status_code == 404
        assert client.get(path + "/photos/" + photo).status_code == 404
        assert client.get("/v1/assessments/latest").status_code == 404
        client.headers["Authorization"] = "Bearer " + users[0]["idToken"]
        assert client.get("/v1/assessments/latest").json()["id"] == aid
        # A durable fence prevents new publication even while a token remains valid.
        response = client.post("/v1/account/deletion")
        assert response.status_code == 202, response.text
        receipt = response.json()["receipt"]
        assert client.get(path).status_code in {401, 403}
        assert client.post(
            "/v1/account/deletion/status", headers={"X-Deletion-Receipt": receipt}
        ).json() == {"status": "pending"}
        accounts = client.app.state.accounts
        accounts.accounts.ref(users[0]["localId"]).update({"accepted_at": time.time() - 400})
        accounts.recover()
        assert client.post(
            "/v1/account/deletion/status", headers={"X-Deletion-Receipt": receipt}
        ).json() == {"status": "complete"}
        assert client.get(path).status_code == 401
        assert (
            client.post(
                "/v1/account/deletion/status", headers={"X-Deletion-Receipt": receipt + "wrong"}
            ).status_code
            == 404
        )
        accounts.recover()  # Idempotent after identity deletion.
        auth.update_user(users[1]["localId"], disabled=True, app=identity.app)
        client.headers["Authorization"] = "Bearer " + users[1]["idToken"]
        assert client.get("/v1/assessments/latest").status_code == 401
        auth.delete_user(users[1]["localId"], app=identity.app)


def test_deletion_retries_failures_and_expired_receipt_recovery(monkeypatch):
    monkeypatch.setenv("FIREBASE_AUTH_EMULATOR_HOST", "127.0.0.1:9099")
    monkeypatch.setenv("FIRESTORE_EMULATOR_HOST", "127.0.0.1:8080")
    config = Settings(
        _env_file=None,
        groq_api_key="test",
        groq_model="test",
        firebase_auth_emulator_host="127.0.0.1:9099",
    )
    identity = FirebaseIdentity(config)
    endpoint = "http://127.0.0.1:9099/identitytoolkit.googleapis.com/v1/accounts:"
    email = f"{uuid4()}@example.test"
    credentials = {"email": email, "password": "Strong-password-123", "returnSecureToken": True}
    user = httpx.post(endpoint + "signUp?key=local", json=credentials).json()
    uid = user["localId"]
    claims = identity.verify(user["idToken"])
    with TestClient(create_app(config, provider=StubProvider(), identity=identity)) as client:
        client.headers["Authorization"] = "Bearer " + user["idToken"]
        real_verify = identity.verify
        identity.verify = lambda token: {**claims, "auth_time": time.time() - 301}
        assert client.post("/v1/account/deletion").status_code == 403
        identity.verify = real_verify
        first = client.post("/v1/account/deletion")
        assert first.status_code == 202  # Unverified accounts can delete too.
        receipt = first.json()["receipt"]
        accounts = client.app.state.accounts
        photos = accounts.photos
        real_delete_photos = photos.delete_account

        def unavailable(_):
            raise OSError("external-service-down")

        photos.delete_account = unavailable
        accounts.recover()
        headers = {"X-Deletion-Receipt": receipt}
        assert (
            client.post("/v1/account/deletion/status", headers=headers).json()["status"]
            == "pending"
        )
        assert auth.get_user(uid, app=identity.app).uid == uid
        client.app.state.annotations.work(uid, str(uuid4()), str(uuid4()))
        from app.errors import AppError
        from app.models.schemas import Photo

        with pytest.raises(AppError, match="deletion"):
            photos.put(uid, str(uuid4()), Photo(sha256="test", content_type="image/jpeg"), b"late")
        photos.delete_account = real_delete_photos
        accounts.accounts.ref(uid).update({"accepted_at": time.time() - 400})
        from google.cloud.firestore_v1.document import DocumentReference

        orphan = (
            accounts.accounts.ref(uid)
            .collection("assessments")
            .document("missing-parent")
            .collection("nested")
            .document("evidence")
        )
        orphan.set({"private": "must be deleted"})
        original_delete = DocumentReference.delete

        def failed_document_delete(document, **kwargs):
            if document.path == orphan.path:
                raise OSError("database-down")
            return original_delete(document, **kwargs)

        monkeypatch.setattr(DocumentReference, "delete", failed_document_delete)
        accounts.recover()
        assert (
            client.post("/v1/account/deletion/status", headers=headers).json()["status"]
            == "pending"
        )
        assert auth.get_user(uid, app=identity.app).uid == uid
        monkeypatch.setattr(DocumentReference, "delete", original_delete)
        real_delete_identity = identity.delete
        identity.delete = unavailable
        accounts.recover()
        assert (
            client.post("/v1/account/deletion/status", headers=headers).json()["status"]
            == "pending"
        )
        identity.delete = real_delete_identity
        operation = receipt.split(".")[0]
        accounts.accounts.client.collection("deletion_operations").document(operation).update(
            {"expires_at": time.time() - 1}
        )
        assert client.post("/v1/account/deletion/status", headers=headers).status_code == 410
        fresh = httpx.post(endpoint + "signInWithPassword?key=local", json=credentials).json()
        client.headers["Authorization"] = "Bearer " + fresh["idToken"]
        recovered = client.post("/v1/account/deletion")
        assert recovered.status_code == 202
        accounts.recover()
        assert (
            client.post(
                "/v1/account/deletion/status",
                headers={"X-Deletion-Receipt": recovered.json()["receipt"]},
            ).json()["status"]
            == "complete"
        )


def test_real_sdk_rejects_expired_wrong_project_anonymous_and_revoked_sessions(monkeypatch):
    monkeypatch.setenv("FIREBASE_AUTH_EMULATOR_HOST", "127.0.0.1:9099")
    monkeypatch.setenv("FIRESTORE_EMULATOR_HOST", "127.0.0.1:8080")
    config = Settings(
        _env_file=None,
        groq_api_key="test",
        groq_model="test",
        firebase_auth_emulator_host="127.0.0.1:9099",
    )
    identity = FirebaseIdentity(config)
    endpoint = "http://127.0.0.1:9099/identitytoolkit.googleapis.com/v1/accounts:"
    credentials = {
        "email": f"{uuid4()}@example.test",
        "password": "Strong-password-123",
        "returnSecureToken": True,
    }
    user = httpx.post(endpoint + "signUp?key=local", json=credentials).json()
    auth.update_user(user["localId"], email_verified=True, app=identity.app)
    token = httpx.post(endpoint + "signInWithPassword?key=local", json=credentials).json()[
        "idToken"
    ]
    anonymous = httpx.post(endpoint + "signUp?key=local", json={"returnSecureToken": True}).json()
    with TestClient(create_app(config, provider=StubProvider(), identity=identity)) as client:

        def status(value):
            return client.get(
                "/v1/assessments/latest", headers={"Authorization": "Bearer " + value}
            ).status_code

        assert status(token) == 404  # Identity is accepted; the history is empty.
        assert status("malformed") == 401
        assert status(anonymous["idToken"]) == 401
        head, payload, signature = token.split(".")
        claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
        for changes in [
            {"exp": int(time.time()) - 3600},
            {"aud": "another-project"},
            {"iss": "https://securetoken.google.com/another-project"},
        ]:
            changed = (
                base64.urlsafe_b64encode(json.dumps({**claims, **changes}).encode())
                .decode()
                .rstrip("=")
            )
            result = status(".".join([head, changed, signature]))
            assert result == 401
        # Distinguish Firebase revocation from our account-deletion fence.
        time.sleep(1.1)
        identity.revoke(user["localId"])
        assert status(token) == 401
        auth.delete_user(user["localId"], app=identity.app)
        auth.delete_user(anonymous["localId"], app=identity.app)
