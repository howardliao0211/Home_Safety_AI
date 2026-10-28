from uuid import uuid4


def path(assessment):
    return (
        f"/v1/assessments/{assessment['id']}/findings/{assessment['findings'][0]['id']}/annotations"
    )


def test_unsupported_configuration_does_not_create_attempt(rig, assessed):
    client, repo, *_ = rig
    response = client.post(path(assessed), json={"revision": "initial"})
    assert response.status_code == 200
    assert response.json() == {
        "state": "unavailable",
        "reason": "MUSE highlighting is unavailable in this configuration.",
        "supported": False,
    }
    stored = repo.get(client.headers["X-Device-ID"], assessed["id"])
    assert stored.annotations == []
    assert client.post(path(assessed), json={"revision": "old"}).status_code == 409
    assert (
        client.post(
            path(assessed), headers={"X-Device-ID": str(uuid4())}, json={"revision": "initial"}
        ).status_code
        == 404
    )


class HighlightProvider:
    def __init__(self):
        self.calls = []
        self.reject = False
        self.invalid = False
        self.no_match = False
        self.on_review = None

    async def select(self, content, evidence, images, deadline):
        from app.annotations.provider import Selection

        self.calls.append("select")
        return Selection(
            photo_id=evidence[0]["photo_id"],
            target="loose cable",
            region={"x": 0.1, "y": 0.2, "width": 0.3, "height": 0.4},
        )

    async def segment(self, data, size, selection, deadline):
        from PIL import Image, ImageDraw

        from app.annotations.provider import Candidate

        self.calls.append("segment")
        if self.no_match:
            return []
        mask = Image.new("L", size if not self.invalid else (1, 1))
        ImageDraw.Draw(mask).rectangle((10, 12, 39, 35), fill=255)
        return [Candidate("7", mask, selection.region)]

    async def review(self, data, content, selection, candidates, deadline):
        from app.annotations.provider import Review

        self.calls.append("review")
        if self.on_review:
            self.on_review()
        return Review(candidate_id=None if self.reject else "7", same_single_object=not self.reject)


def enabled(rig):
    client, *_ = rig
    svc = client.app.state.annotations
    provider = HighlightProvider()
    svc.provider = provider
    return svc, provider


def test_reviewed_result_reused_feedback_and_explicit_retry(rig, assessed):
    client, repo, photos, _ = rig
    svc, provider = enabled(rig)
    base = path(assessed)
    job = client.post(base, json={"revision": "initial"}).json()
    assert job["state"] == "queued"
    assert provider.calls == []  # HTTP requests never drive execution.
    assert client.post(base, json={"revision": "initial", "retry": True}).json()["id"] == job["id"]
    device = client.headers["X-Device-ID"]
    svc.work(device, assessed["id"])
    svc.work(device, assessed["id"])
    ready = client.get(base + "/" + job["id"]).json()
    assert ready["state"] == "ready"
    assert ready["review"] == "approved"
    assert provider.calls == ["select", "segment", "review"]
    assert not {"mask", "lease_id", "request_id", "expires_at"}.intersection(ready)
    mask = client.get(base + "/" + job["id"] + "/mask")
    assert mask.status_code == 200
    assert mask.headers["content-type"] == "image/png"
    assert client.post(base, json={"revision": "initial"}).json()["id"] == job["id"]
    report = base + "/" + job["id"] + "/feedback"
    for _ in range(2):
        assert client.post(report, json={"kind": "wrong_object"}).json()["state"] == "reported"
    assert client.get(base + "/" + job["id"] + "/mask").status_code == 404
    current = client.get(f"/v1/assessments/{assessed['id']}").json()["findings"][0]
    assert (
        current["status"] == "open" and current["evidence"] == assessed["findings"][0]["evidence"]
    )
    assert client.post(base, json={"revision": "initial"}).json()["state"] == "reported"
    retried = client.post(base, json={"revision": "initial", "retry": True}).json()
    assert retried["id"] != job["id"] and retried["attempt"] == 2
    assert (
        client.post(base, json={"revision": "initial", "retry": True}).json()["id"] == retried["id"]
    )


def test_rejected_and_invalid_masks_never_published(rig, assessed):
    client, *_ = rig
    svc, provider = enabled(rig)
    base = path(assessed)
    provider.reject = True
    first = client.post(base, json={"revision": "initial"}).json()
    svc.work(client.headers["X-Device-ID"], assessed["id"])
    assert client.get(base + "/" + first["id"]).json()["state"] == "unavailable"
    assert client.get(base + "/" + first["id"] + "/mask").status_code == 404
    provider.invalid = True
    second = client.post(base, json={"revision": "initial", "retry": True}).json()
    svc.work(client.headers["X-Device-ID"], assessed["id"])
    assert client.get(base + "/" + second["id"]).json()["state"] == "failed"
    assert provider.calls == ["select", "segment", "review", "select", "segment"]


def test_stale_publication_fenced_and_history_retained(rig, assessed):
    from conftest import content

    client, repo, _, safety = rig
    svc, provider = enabled(rig)
    base = path(assessed)
    finding_url = base.removesuffix("/annotations")
    job = client.post(base, json={"revision": "initial"}).json()
    # Checklist changes do not alter content identity.
    patched = client.patch(finding_url, json={"status": "resolved", "note": "done"}).json()
    assert patched["findings"][0]["content_revision"] == "initial"
    submitted = client.post(
        finding_url + "/submissions",
        data={"submission_id": str(uuid4()), "kind": "follow-up", "text": "Yes"},
    ).json()
    submission = submitted["findings"][0]["submissions"][0]
    safety.results.append(
        {
            "finding": {**content(), "evidence": "The same cable remains visible."},
            "feedback": "Context updated.",
        }
    )
    provider.on_review = lambda: client.post(
        finding_url + f"/submissions/{submission['id']}/analyze"
    )
    svc.work(client.headers["X-Device-ID"], assessed["id"])
    assert client.get(base + "/" + job["id"]).json()["state"] == "failed"
    revised = client.get(f"/v1/assessments/{assessed['id']}").json()["findings"][0]
    assert revised["content_revision"] != "initial"
    assert revised["annotation"] is None
    assert (
        revised["evidence_history"][0]["content"]["evidence"] == assessed["findings"][0]["evidence"]
    )
    assert client.post(base, json={"revision": "initial"}).status_code == 409


def test_deletion_during_review_cannot_restore_record_or_asset(rig, assessed):
    client, repo, photos, _ = rig
    svc, provider = enabled(rig)
    client.post(path(assessed), json={"revision": "initial"})
    provider.on_review = lambda: client.delete(f"/v1/assessments/{assessed['id']}")
    svc.work(client.headers["X-Device-ID"], assessed["id"])
    assert client.get(f"/v1/assessments/{assessed['id']}").status_code == 404
    assert not photos.objects


def test_expired_worker_claim_does_not_repeat_attempt(rig, assessed):
    from datetime import timedelta

    from app.models.schemas import now

    client, repo, *_ = rig
    svc, provider = enabled(rig)
    base = path(assessed)
    job = client.post(base, json={"revision": "initial"}).json()
    device = client.headers["X-Device-ID"]

    def lost(a):
        a.annotations[0].state = "processing"
        a.annotations[0].expires_at = now() - timedelta(seconds=1)
        return a

    repo.mutate(device, assessed["id"], lost)
    svc.work(device, assessed["id"])
    assert provider.calls == []
    assert client.get(base + "/" + job["id"]).json()["state"] == "failed"


def test_annotation_operations_are_device_scoped_and_worker_requires_service_auth(rig, assessed):
    client, *_ = rig
    svc, _ = enabled(rig)
    base = path(assessed)
    job = client.post(base, json={"revision": "initial"}).json()
    svc.work(client.headers["X-Device-ID"], assessed["id"])
    other = {"X-Device-ID": str(uuid4())}
    for suffix in ("", "/mask"):
        assert client.get(base + "/" + job["id"] + suffix, headers=other).status_code == 404
    assert (
        client.post(
            base + "/" + job["id"] + "/feedback", headers=other, json={"kind": "wrong_object"}
        ).status_code
        == 404
    )
    assert (
        client.post(
            "/internal/annotations/work",
            json={"device_id": other["X-Device-ID"], "assessment_id": assessed["id"]},
        ).status_code
        == 401
    )


def test_deadline_discards_late_output_and_releases_queue(rig, assessed, monkeypatch):
    import asyncio

    import app.annotations.service as module

    client, *_ = rig
    svc, provider = enabled(rig)
    original = provider.segment

    async def slow(*args):
        await asyncio.sleep(0.2)
        return await original(*args)

    provider.segment = slow
    monkeypatch.setattr(module, "BUDGET_SECONDS", 0.03)
    base = path(assessed)
    job = client.post(base, json={"revision": "initial"}).json()
    svc.work(client.headers["X-Device-ID"], assessed["id"])
    assert client.get(base + "/" + job["id"]).json()["state"] == "failed"
    assert provider.calls == ["select"]
    assert client.post(base, json={"revision": "initial"}).json()["id"] == job["id"]


def test_fifo_and_duplicate_delivery_do_not_start_parallel_jobs(rig, create):
    import threading

    from conftest import assessment_result

    client, repo, _, safety = rig
    result = assessment_result()
    result["findings"].append({**result["findings"][0], "title": "Second cable"})
    safety.results.append(result)
    a = create()
    assessed = client.post(f"/v1/assessments/{a['id']}/analyze").json()
    svc, provider = enabled(rig)
    base = path(assessed)
    first = client.post(base, json={"revision": "initial"}).json()
    second_base = base.replace(assessed["findings"][0]["id"], assessed["findings"][1]["id"])
    second = client.post(second_base, json={"revision": "initial"}).json()
    entered, release = threading.Event(), threading.Event()

    async def blocked(*args):
        import asyncio

        entered.set()
        await asyncio.to_thread(release.wait, 2)
        from app.annotations.provider import Review

        return Review(candidate_id="7", same_single_object=True)

    provider.review = blocked
    device = client.headers["X-Device-ID"]
    worker = threading.Thread(target=svc.work, args=(device, assessed["id"], first["id"]))
    worker.start()
    assert entered.wait(2)
    svc.work(device, assessed["id"], first["id"])
    svc.work(device, assessed["id"], second["id"])
    assert provider.calls == ["select", "segment"]
    assert client.get(second_base + "/" + second["id"]).json()["state"] == "queued"
    release.set()
    worker.join(3)
    svc.work(device, assessed["id"], first["id"])
    assert provider.calls == ["select", "segment"]
    svc.work(device, assessed["id"], second["id"])
    assert provider.calls == ["select", "segment", "select", "segment"]
    assert client.get(second_base + "/" + second["id"]).json()["state"] == "ready"


def test_dispatch_failure_leaves_recoverable_intent(rig, assessed):
    client, repo, *_ = rig
    svc, provider = enabled(rig)

    class BrokenDispatch:
        def enqueue(self, *args):
            raise ConnectionError("dispatch down")

    svc.dispatcher = BrokenDispatch()
    job = client.post(path(assessed), json={"revision": "initial"}).json()
    assert job["state"] == "queued" and provider.calls == []
    pending = repo.annotation_pending()
    assert len(pending) == 1 and pending[0].id == assessed["id"]
    svc.dispatcher = None
    svc.recover()  # Same local worker transitions after backend restart.
    assert client.get(path(assessed) + "/" + job["id"]).json()["state"] == "ready"


def test_worker_decodes_documented_sam_wire_format_before_review(rig, assessed):
    import json

    import httpx

    from app.annotations.provider import MuseHighlightProvider
    from app.config import Settings

    client, *_ = rig
    svc = client.app.state.annotations
    config = Settings(
        _env_file=None,
        model_provider="muse",
        muse_api_key="private-key",
        muse_main_model="main",
        muse_segmentation_model="sam-3.1",
    )
    adapter = MuseHighlightProvider(config)
    calls = []
    photo_id = assessed["photo"]["id"]
    # Published example in Meta's reading-segmentation documentation (lossless
    # raster 27x60), placed at a known in-bounds box in this fixture photo.
    wire = "<0f>0<|box;x1=11;y1=22;x2=70;y2=48;w=100;h=60|><|mask;x=0;y=0;data=27,60,~!!!!M!0c[0o91w?q1!pIH4pPRVp2B3'7`e.ioeAf6-k/#Xd8%dX9x(|>"

    def transport(request):
        payload = json.loads(request.content)
        calls.append(payload)
        if payload["model"] == "sam-3.1":
            events = [
                {"type": "response.output_text.delta", "delta": wire},
                {"type": "response.completed"},
            ]
            return httpx.Response(
                200, text="".join("data: " + json.dumps(e) + "\n\n" for e in events)
            )
        result = (
            {
                "photo_id": photo_id,
                "target": "loose cable",
                "region": {"x": 0.1, "y": 0.2, "width": 0.5, "height": 0.5},
            }
            if len(calls) == 1
            else {"candidate_id": "0", "same_single_object": True}
        )
        return httpx.Response(
            200,
            json={
                "status": "completed",
                "output": [
                    {
                        "type": "message",
                        "content": [{"type": "output_text", "text": json.dumps(result)}],
                    }
                ],
            },
        )

    adapter.client = lambda deadline: httpx.AsyncClient(
        base_url="https://api.meta.ai/v1/", transport=httpx.MockTransport(transport)
    )
    svc.provider = adapter
    base = path(assessed)
    job = client.post(base, json={"revision": "initial"}).json()
    svc.work(client.headers["X-Device-ID"], assessed["id"])
    saved = client.get(base + "/" + job["id"]).json()
    assert saved["state"] == "ready", saved
    assert [c["model"] for c in calls] == ["main", "sam-3.1", "main"]
    assert saved["region"] == {"x": 0.11, "y": 22 / 60, "width": 0.6, "height": 0.45}
    assert client.get(base + "/" + job["id"] + "/mask").status_code == 200


def test_durable_dispatch_uses_service_oidc_and_worker_redelivery_is_idempotent(
    rig, assessed, monkeypatch
):
    import json

    import app.annotations.dispatch as module

    client, *_ = rig
    svc, provider = enabled(rig)
    settings = client.app.state.settings
    settings.annotation_worker_url = "https://demo.run.app"
    settings.annotation_worker_service_account = "worker@example.iam.gserviceaccount.com"
    settings.annotation_tasks_queue = "projects/demo/locations/us-central1/queues/annotations"
    deliveries = []

    class Tasks:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def create_task(self, **kwargs):
            deliveries.append(kwargs)

    monkeypatch.setattr(module.tasks_v2, "CloudTasksClient", Tasks)
    svc.dispatcher = module.CloudTasksDispatcher(settings)
    job = client.post(path(assessed), json={"revision": "initial"}).json()
    dispatched = deliveries[0]["task"]["http_request"]
    assert dispatched["url"] == "https://demo.run.app/internal/annotations/work"
    assert dispatched["oidc_token"] == {
        "service_account_email": settings.annotation_worker_service_account,
        "audience": settings.annotation_worker_url,
    }
    body = json.loads(dispatched["body"])
    assert body["annotation_id"] == job["id"]
    assert provider.calls == []
    monkeypatch.setattr(
        module.id_token,
        "verify_oauth2_token",
        lambda *args, **kwargs: {
            "email": settings.annotation_worker_service_account,
            "email_verified": True,
        },
    )
    headers = {"Authorization": "Bearer signed-service-token"}
    assert client.post("/internal/annotations/recover", headers=headers).status_code == 200
    assert provider.calls == []
    for _ in range(2):
        assert (
            client.post("/internal/annotations/work", headers=headers, json=body).status_code == 200
        )
    assert provider.calls == ["select", "segment", "review"]
    monkeypatch.setattr(
        module.id_token,
        "verify_oauth2_token",
        lambda *args, **kwargs: {"email": "attacker@example.com", "email_verified": True},
    )
    assert client.post("/internal/annotations/work", headers=headers, json=body).status_code == 401


def test_no_match_saves_selected_source_and_stays_terminal_on_open(rig, assessed):
    client, *_ = rig
    svc, provider = enabled(rig)
    provider.no_match = True
    base = path(assessed)
    job = client.post(base, json={"revision": "initial"}).json()
    svc.work(client.headers["X-Device-ID"], assessed["id"])
    saved = client.get(base + "/" + job["id"]).json()
    assert saved["state"] == "unavailable"
    assert saved["photo_id"] == assessed["photo"]["id"]
    assert saved["image_digest"] == assessed["photo"]["sha256"]
    assert saved["width"] == 100 and saved["height"] == 60
    assert client.post(base, json={"revision": "initial"}).json()["id"] == job["id"]
    assert provider.calls == ["select", "segment"]
