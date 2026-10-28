"""Account authentication at the HTTP boundary."""

from uuid import uuid4


def test_device_headers_and_demo_tokens_cannot_authenticate(rig):
    client, *_ = rig
    client.headers.pop("Authorization", None)
    assert client.get("/v1/assessments/latest").status_code == 401
    client.headers["Authorization"] = "Bearer old-demo-token"
    assert client.get("/v1/assessments/latest").status_code == 401
    assert client.get("/health").json() == {"status": "ok"}


def test_unverified_accounts_cannot_access_assessments(rig):
    client, *_ = rig
    client.app.state.identity.verify = lambda _: {"uid": "opaque/user", "email_verified": False}
    response = client.get("/v1/assessments/latest")
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "email_unverified"


def test_owner_is_opaque_and_every_child_route_is_isolated(rig, create):
    client, *_ = rig
    client.app.state.identity.verify = lambda token: {"uid": token, "email_verified": True}
    client.headers["Authorization"] = "Bearer opaque/user:A"
    assessment = create()
    base = f"/v1/assessments/{assessment['id']}"
    assessed = client.post(base + "/analyze").json()
    finding = base + f"/findings/{assessed['findings'][0]['id']}"
    annotation = finding + f"/annotations/{uuid4()}"
    client.headers["Authorization"] = "Bearer opaque/user:B"
    for method, path, body in [
        ("GET", base, None),
        ("POST", base + "/analyze", None),
        ("GET", base + "/photos/" + assessment["photo"]["id"], None),
        ("PATCH", finding, {"status": "resolved"}),
        ("POST", finding + "/skip-follow-up", None),
        ("GET", annotation, None),
        ("GET", annotation + "/mask", None),
        ("POST", annotation + "/feedback", {"kind": "wrong_object"}),
    ]:
        assert client.request(method, path, json=body).status_code == 404, path
    # Same account on a different installation reopens its latest assessment.
    client.headers["Authorization"] = "Bearer opaque/user:A"
    client.headers["X-Device-ID"] = "anything"
    assert client.get("/v1/assessments/latest").json()["id"] == assessment["id"]
