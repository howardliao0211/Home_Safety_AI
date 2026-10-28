from uuid import uuid4

from conftest import assessment_result


def path(assessment, index=0):
    finding = assessment["findings"][index]["id"]
    return f"/v1/assessments/{assessment['id']}/findings/{finding}/annotations"


class HighlightProvider:
    """Fake SAM adapter: one concept prompt in, ranked-later candidates out."""

    def __init__(self):
        self.calls = []
        self.candidates = None  # None means one valid unscored candidate.
        self.on_segment = None

    async def segment(self, data, size, prompt, deadline):
        self.calls.append(prompt)
        if self.on_segment:
            await self.on_segment(prompt)
        if self.candidates is not None:
            return self.candidates(size) if callable(self.candidates) else self.candidates
        return [candidate("7", size)]


def candidate(object_id, size, box=(10, 12, 39, 35), confidence=None):
    from PIL import Image, ImageDraw

    from app.annotations.provider import Candidate
    from app.models.schemas import Region

    w, h = size
    mask = Image.new("L", size)
    ImageDraw.Draw(mask).rectangle((box[0], box[1], box[2] - 1, box[3] - 1), fill=255)
    region = Region(
        x=box[0] / w, y=box[1] / h, width=(box[2] - box[0]) / w, height=(box[3] - box[1]) / h
    )
    return Candidate(object_id, mask, region, confidence)


def enabled(rig):
    client, *_ = rig
    svc = client.app.state.annotations
    provider = HighlightProvider()
    svc.provider = provider
    return svc, provider


def analyze(rig, create, result):
    client, _, _, safety = rig
    safety.results.append(result)
    a = create()
    response = client.post(f"/v1/assessments/{a['id']}/analyze")
    assert response.status_code == 200, response.text
    return response.json()


def findings(*prompts):
    result = assessment_result()
    base = result["findings"][0]
    result["findings"] = [
        {**base, "title": f"Finding {i}", "segmentation_prompt": prompt}
        for i, prompt in enumerate(prompts)
    ]
    return result


def test_completed_assessment_queues_one_attempt_per_eligible_finding(rig, create):
    client, repo, _, safety = rig
    svc, provider = enabled(rig)
    result = findings("black power cable", None, "   ", "x" * 201)
    del result["findings"][1]["segmentation_prompt"]  # Missing is tolerated too.
    assessed = analyze(rig, create, result)
    assert len(safety.calls) == 1 and provider.calls == []  # No extra model calls.
    jobs = [f["annotation"] for f in assessed["findings"]]
    assert jobs[0]["state"] == "queued" and jobs[0]["id"]
    assert jobs[0]["photo_id"] == assessed["photo"]["id"]
    assert [j["state"] for j in jobs[1:]] == ["unavailable"] * 3
    assert all(j["reason"] for j in jobs[1:])
    assert "prompt" not in jobs[0] and "segmentation_prompt" not in assessed["findings"][0]
    stored = repo.get(client.headers["X-Device-ID"], assessed["id"])
    assert stored.annotation_dispatch_pending
    assert [j.prompt for j in stored.annotations] == ["black power cable", None, None, None]
    # Repeating a completed analysis never duplicates attempts.
    client.post(f"/v1/assessments/{assessed['id']}/analyze")
    assert len(repo.get(client.headers["X-Device-ID"], assessed["id"]).annotations) == 4


def test_worker_segments_saved_prompt_and_retry_never_calls_main_model(rig, assessed):
    client, repo, photos, safety = rig
    svc, provider = enabled(rig)
    calls = len(safety.calls)
    base = path(assessed)
    job = assessed["findings"][0]["annotation"]
    assert job["state"] == "unavailable"  # Assessed before highlighting was enabled.
    retried = client.post(base, json={"revision": "initial", "retry": True}).json()
    assert retried["state"] == "queued" and retried["attempt"] == 2
    # Rapid retry taps reuse the active attempt.
    assert (
        client.post(base, json={"revision": "initial", "retry": True}).json()["id"] == retried["id"]
    )
    assert provider.calls == []  # HTTP requests never drive execution.
    device = client.headers["X-Device-ID"]
    svc.work(device, assessed["id"], retried["id"])
    svc.work(device, assessed["id"], retried["id"])  # Duplicate delivery.
    ready = client.get(base + "/" + retried["id"]).json()
    assert ready["state"] == "ready" and ready["width"] == 100 and ready["height"] == 60
    assert ready["region"] == {"x": 0.1, "y": 0.2, "width": 0.29, "height": 23 / 60}
    assert provider.calls == ["black power cable"] and len(safety.calls) == calls
    assert not {"mask", "lease_id", "request_id", "expires_at", "prompt"}.intersection(ready)
    mask = client.get(base + "/" + retried["id"] + "/mask")
    assert mask.status_code == 200 and mask.headers["content-type"] == "image/png"
    report = base + "/" + retried["id"] + "/feedback"
    for _ in range(2):
        assert client.post(report, json={"kind": "wrong_object"}).json()["state"] == "reported"
    assert client.get(base + "/" + retried["id"] + "/mask").status_code == 404
    current = client.get(f"/v1/assessments/{assessed['id']}").json()["findings"][0]
    assert current["status"] == "open" and current["annotation"]["state"] == "reported"
    assert current["evidence"] == assessed["findings"][0]["evidence"]
    again = client.post(base, json={"revision": "initial", "retry": True}).json()
    assert again["attempt"] == 3 and provider.calls == ["black power cable"]


def test_unsupported_configuration_is_explicit_and_creates_no_sam_work(rig, assessed):
    client, repo, *_ = rig
    job = assessed["findings"][0]["annotation"]
    assert job["state"] == "unavailable"
    assert job["reason"] == "MUSE highlighting is unavailable in this configuration."
    base = path(assessed)
    response = client.post(base, json={"revision": "initial", "retry": True})
    assert response.status_code == 200
    assert response.json()["supported"] is False
    stored = repo.get(client.headers["X-Device-ID"], assessed["id"])
    assert len(stored.annotations) == 1 and not stored.annotation_dispatch_pending
    assert client.post(base, json={"revision": "old", "retry": True}).status_code == 409
    other = {"X-Device-ID": str(uuid4())}
    assert client.post(base, headers=other, json={"revision": "initial"}).status_code == 404


def test_slow_attempt_does_not_block_sibling_from_reaching_ready(rig, create):
    import asyncio
    import threading

    client, *_ = rig
    svc, provider = enabled(rig)
    assessed = analyze(rig, create, findings("slow heater", "black power cable"))
    slow, fast = (f["annotation"]["id"] for f in assessed["findings"])
    entered, release = threading.Event(), threading.Event()

    async def hold(prompt):
        if prompt == "slow heater":
            entered.set()
            await asyncio.to_thread(release.wait, 5)

    provider.on_segment = hold
    device = client.headers["X-Device-ID"]
    worker = threading.Thread(target=svc.work, args=(device, assessed["id"], slow))
    worker.start()
    assert entered.wait(5)
    svc.work(device, assessed["id"], slow)  # Duplicate delivery while started: no-op.
    svc.recover()  # Recovery sweep cannot restart the started attempt either.
    svc.work(device, assessed["id"], fast)
    states = {
        f["annotation"]["id"]: f["annotation"]["state"]
        for f in client.get(f"/v1/assessments/{assessed['id']}").json()["findings"]
    }
    assert states == {slow: "processing", fast: "ready"}
    release.set()
    worker.join(5)
    assert client.get(path(assessed) + "/" + slow).json()["state"] == "ready"
    assert sorted(provider.calls) == ["black power cable", "slow heater"]


def overlapping(count):
    """Provider hook that only proceeds once every attempt is inside SAM at once."""
    import asyncio
    import threading

    barrier = threading.Barrier(count, timeout=10)

    async def wait(prompt):
        await asyncio.to_thread(barrier.wait)

    return wait


def test_local_worker_runs_twelve_findings_concurrently(rig, create):
    from app.annotations.local_worker import LocalWorker

    client, repo, *_ = rig
    svc, provider = enabled(rig)
    assessed = analyze(rig, create, findings(*[f"object {i}" for i in range(12)]))
    provider.on_segment = overlapping(12)
    worker = LocalWorker(svc)
    try:
        worker.tick()
        worker.tick()  # In-flight attempts are not submitted twice.
        worker.drain(30)
    finally:
        worker.close()
    saved = client.get(f"/v1/assessments/{assessed['id']}").json()["findings"]
    assert [f["annotation"]["state"] for f in saved] == ["ready"] * 12
    assert len(provider.calls) == 12
    assert not repo.get(client.headers["X-Device-ID"], assessed["id"]).annotation_dispatch_pending


def test_cloud_tasks_path_enqueues_each_finding_and_deliveries_overlap(rig, create, monkeypatch):
    import json
    from concurrent.futures import ThreadPoolExecutor

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
    monkeypatch.setattr(
        module.id_token,
        "verify_oauth2_token",
        lambda *args, **kwargs: {
            "email": settings.annotation_worker_service_account,
            "email_verified": True,
        },
    )
    svc.dispatcher = module.CloudTasksDispatcher(settings)
    assessed = analyze(rig, create, findings(*[f"object {i}" for i in range(12)]))
    bodies = [json.loads(d["task"]["http_request"]["body"]) for d in deliveries]
    assert sorted(b["annotation_id"] for b in bodies) == sorted(
        f["annotation"]["id"] for f in assessed["findings"]
    )
    assert deliveries[0]["task"]["http_request"]["oidc_token"] == {
        "service_account_email": settings.annotation_worker_service_account,
        "audience": settings.annotation_worker_url,
    }
    assert provider.calls == []
    provider.on_segment = overlapping(12)
    headers = {"Authorization": "Bearer signed-service-token"}
    with ThreadPoolExecutor(12) as pool:
        codes = list(
            pool.map(
                lambda body: (
                    client.post(
                        "/internal/annotations/work", headers=headers, json=body
                    ).status_code
                ),
                bodies,
            )
        )
    assert codes == [200] * 12 and len(provider.calls) == 12
    # Redelivery of finished work never repeats a provider call.
    assert (
        client.post("/internal/annotations/work", headers=headers, json=bodies[0]).status_code
        == 200
    )
    assert client.post("/internal/annotations/recover", headers=headers).status_code == 200
    assert len(provider.calls) == 12
    saved = client.get(f"/v1/assessments/{assessed['id']}").json()["findings"]
    assert [f["annotation"]["state"] for f in saved] == ["ready"] * 12
    monkeypatch.setattr(
        module.id_token,
        "verify_oauth2_token",
        lambda *args, **kwargs: {"email": "attacker@example.com", "email_verified": True},
    )
    assert (
        client.post("/internal/annotations/work", headers=headers, json=bodies[0]).status_code
        == 401
    )


# Published lossless 60x27 mask from Meta's reading-segmentation documentation.
MASK = "data=27,60,~!!!!M!0c[0o91w?q1!pIH4pPRVp2B3'7`e.ioeAf6-k/#Xd8%dX9x("


def record(object_id, x, y, c=None, data=MASK, w=100, h=60):
    score = "" if c is None else f";c={c}"
    return (
        f"{object_id}<|box;x1={x};y1={y};x2={x + 59};y2={y + 26};w={w};h={h}{score}|>"
        f"<|mask;x=0;y=0;{data}{score}|>"
    )


def sam(rig, *records, raw=None):
    """Run the real SAM adapter against a mocked stream; return (chosen, requests)."""
    import asyncio
    import json
    import time

    import httpx

    from app.annotations.provider import MuseHighlightProvider, choose
    from app.config import Settings

    config = Settings(
        _env_file=None,
        model_provider="muse",
        muse_api_key="private-key",
        muse_main_model="main",
        muse_segmentation_model="sam-3.1",
    )
    adapter = MuseHighlightProvider(config)
    requests = []
    text = raw if raw is not None else ("<0f>" + ",".join(records) if records else "")

    def transport(request):
        requests.append(json.loads(request.content))
        events = [{"type": "response.output_text.delta", "delta": text}] if text else []
        events.append({"type": "response.completed"})
        return httpx.Response(200, text="".join("data: " + json.dumps(e) + "\n\n" for e in events))

    adapter.client = lambda deadline: httpx.AsyncClient(
        base_url="https://api.meta.ai/v1/", transport=httpx.MockTransport(transport)
    )
    candidates = asyncio.run(
        adapter.segment(b"photo", (100, 60), "curtains", time.monotonic() + 10)
    )
    return (choose(candidates, (100, 60)) if candidates else None), requests


def test_sam_request_is_one_concept_prompt_with_confidence(rig):
    chosen, requests = sam(rig, record("0", 11, 22))
    assert len(requests) == 1
    body = requests[0]
    assert body["model"] == "sam-3.1"
    assert body["metadata"] == {"mask_encoding": "one_bit", "include_confidence": "true"}
    content = body["input"][0]["content"]
    assert content[0] == {"type": "input_text", "text": "curtains"}
    assert content[1]["type"] == "input_image"
    assert chosen.region.model_dump() == {"x": 0.11, "y": 22 / 60, "width": 0.6, "height": 0.45}


def test_highest_valid_score_wins_and_ties_or_absent_scores_keep_provider_order(rig):
    mixed, _ = sam(rig, record("5", 0, 0), record("1", 20, 20, 0.4), record("9", 40, 33, 0.9))
    assert (mixed.id, mixed.confidence) == ("9", 0.9)
    tied, _ = sam(rig, record("3", 0, 0, 0.8), record("2", 40, 33, 0.8))
    assert tied.id == "3"
    absent, _ = sam(rig, record("9", 0, 0), record("1", 40, 33))
    assert (absent.id, absent.confidence) == ("9", None)  # IDs are never scores.
    invalid, _ = sam(rig, record("4", 0, 0, 1.5), record("6", 40, 33, 0.2))
    assert invalid.id == "6"  # An out-of-range score counts as absent.


def test_invalid_candidates_are_excluded_but_untrustworthy_output_fails(rig):
    import pytest

    bad_mask = record("1", 0, 0, 0.99, data="data=27,60,~!!!")
    chosen, _ = sam(rig, bad_mask, record("3", 20, 20, 0.1))
    assert chosen.id == "3"
    with pytest.raises(ValueError):
        sam(rig, bad_mask)  # Nothing valid remains.
    with pytest.raises(ValueError):
        sam(rig, record("3", 20, 20, 0.1), record("2", 60, 40, 0.98))  # Malformed geometry.
    with pytest.raises(ValueError):
        sam(rig, record("1", 0, 0, w=200))  # Source dimensions disagree.
    with pytest.raises(ValueError):
        sam(rig, raw="<0f>not a record")
    with pytest.raises(ValueError):
        sam(rig, record("1", 0, 0), record("1", 40, 33))  # Duplicate object IDs.
    with pytest.raises(ValueError):
        sam(rig, *[record(str(i), 0, 0) for i in range(33)])  # No silent truncation.
    assert sam(rig) == (None, sam(rig)[1])  # Zero matches is not an error.


def queued(rig, create, *prompts):
    svc, provider = enabled(rig)
    assessed = analyze(rig, create, findings(*(prompts or ("black power cable",))))
    return svc, provider, assessed, [f["annotation"]["id"] for f in assessed["findings"]]


def test_worker_publishes_only_the_highest_scored_valid_candidate(rig, create):
    client, *_ = rig
    svc, provider, assessed, (job,) = queued(rig, create)
    provider.candidates = lambda size: [
        candidate("1", size, (0, 0, 20, 20), 0.3),
        candidate("2", size, (50, 30, 90, 55), 0.95),
        candidate("3", size, (20, 20, 40, 40), None),
    ]
    svc.work(client.headers["X-Device-ID"], assessed["id"], job)
    saved = client.get(path(assessed) + "/" + job).json()
    assert saved["state"] == "ready" and saved["confidence"] == 0.95
    assert saved["region"] == {"x": 0.5, "y": 0.5, "width": 0.4, "height": 25 / 60}


def test_failure_or_no_match_affects_only_its_own_finding(rig, create):
    client, *_ = rig
    svc, provider, assessed, jobs = queued(rig, create, "broken", "absent", "black power cable")

    async def outcome(prompt):
        if prompt == "broken":
            raise ConnectionError("provider down")

    provider.on_segment = outcome
    provider.candidates = lambda size: (
        [] if provider.calls[-1] == "absent" else [candidate("7", size)]
    )
    for job in jobs:
        svc.work(client.headers["X-Device-ID"], assessed["id"], job)
    states = [client.get(path(assessed, i) + "/" + j).json()["state"] for i, j in enumerate(jobs)]
    assert states == ["failed", "unavailable", "ready"]


def test_deadline_fails_only_the_slow_attempt(rig, create, monkeypatch):
    import asyncio

    import app.annotations.service as module

    client, *_ = rig
    svc, provider, assessed, (slow, fast) = queued(rig, create, "slow", "fast")

    async def stall(prompt):
        if prompt == "slow":
            await asyncio.sleep(10)

    provider.on_segment = stall
    # Leaves the fast sibling time to spawn its mask process on a loaded machine.
    monkeypatch.setattr(module, "BUDGET_SECONDS", 3)
    svc.work(client.headers["X-Device-ID"], assessed["id"], slow)
    svc.work(client.headers["X-Device-ID"], assessed["id"], fast)
    assert client.get(path(assessed) + "/" + slow).json()["state"] == "failed"
    assert client.get(path(assessed, 1) + "/" + fast).json()["state"] == "ready"


def test_follow_up_revision_fences_stale_job_and_never_segments(rig, create):
    from conftest import content

    client, repo, _, safety = rig
    svc, provider, assessed, (job,) = queued(rig, create)
    base = path(assessed)
    finding_url = base.removesuffix("/annotations")
    # Checklist changes do not alter content identity or rerun segmentation.
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

    async def revise(prompt):
        import asyncio

        await asyncio.to_thread(
            client.post, finding_url + f"/submissions/{submission['id']}/analyze"
        )

    provider.on_segment = revise
    svc.work(client.headers["X-Device-ID"], assessed["id"], job)
    assert client.get(base + "/" + job).json()["state"] == "failed"
    revised = client.get(f"/v1/assessments/{assessed['id']}").json()["findings"][0]
    assert revised["content_revision"] != "initial" and revised["annotation"] is None
    assert revised["annotations"][0]["revision"] == "initial"  # History is kept.
    assert (
        revised["evidence_history"][0]["content"]["evidence"] == assessed["findings"][0]["evidence"]
    )
    stored = repo.get(client.headers["X-Device-ID"], assessed["id"])
    assert len(stored.annotations) == 1 and not stored.annotation_dispatch_pending
    for retry in (False, True):
        response = client.post(base, json={"revision": revised["content_revision"], "retry": retry})
        assert response.status_code == 409
    assert provider.calls == ["black power cable"]


def test_deletion_cancels_queued_work_and_fences_concurrent_publishers(rig, create):
    client, repo, photos, _ = rig
    svc, provider, assessed, (running, waiting) = queued(rig, create, "first", "second")

    async def delete(prompt):
        import asyncio

        await asyncio.to_thread(client.delete, f"/v1/assessments/{assessed['id']}")

    provider.on_segment = delete
    svc.work(client.headers["X-Device-ID"], assessed["id"], running)
    svc.work(client.headers["X-Device-ID"], assessed["id"], waiting)
    assert client.get(f"/v1/assessments/{assessed['id']}").status_code == 404
    assert provider.calls == ["first"] and not photos.objects


def test_expired_started_attempt_becomes_retryable_failure_without_repeat(rig, create):
    from datetime import timedelta

    from app.models.schemas import now

    client, repo, *_ = rig
    svc, provider, assessed, (job,) = queued(rig, create)
    device = client.headers["X-Device-ID"]

    def lost(a):
        a.annotations[0].state = "processing"
        a.annotations[0].expires_at = now() - timedelta(seconds=1)
        return a

    repo.mutate(device, assessed["id"], lost)
    svc.recover()
    saved = client.get(path(assessed) + "/" + job).json()
    assert provider.calls == [] and saved["state"] == "failed" and saved["retryable"]


def test_dispatch_outage_keeps_assessment_and_recovers_without_duplicates(rig, create):
    client, repo, *_ = rig
    svc, provider = enabled(rig)

    class BrokenDispatch:
        def enqueue(self, *args):
            raise ConnectionError("dispatch down")

    svc.dispatcher = BrokenDispatch()
    assessed = analyze(rig, create, findings("first", "second"))
    assert assessed["status"] == "complete"
    assert [f["annotation"]["state"] for f in assessed["findings"]] == ["queued", "queued"]
    assert [a.id for a in repo.annotation_pending()] == [assessed["id"]]
    svc.dispatcher = None
    svc.recover()  # Same transitions after a backend restart.
    svc.recover()
    assert sorted(provider.calls) == ["first", "second"]
    saved = client.get(f"/v1/assessments/{assessed['id']}").json()["findings"]
    assert [f["annotation"]["state"] for f in saved] == ["ready", "ready"]


def test_legacy_attempt_without_prompt_stays_readable_and_is_not_retried(rig, create):
    client, repo, *_ = rig
    svc, provider, assessed, (job,) = queued(rig, create)
    device = client.headers["X-Device-ID"]

    def legacy(a):
        a.annotations[0].prompt = None
        a.annotations[0].state, a.annotations[0].review = "unavailable", "rejected"
        return a

    repo.mutate(device, assessed["id"], legacy)
    saved = client.get(path(assessed) + "/" + job).json()
    assert saved["state"] == "unavailable" and saved["retryable"] is False
    response = client.post(path(assessed), json={"revision": "initial", "retry": True})
    assert response.status_code == 409 and response.json()["error"]["code"] == "retry_unavailable"
    assert provider.calls == []


def test_late_publication_commit_is_never_visible_as_ready(rig, create):
    from datetime import timedelta

    client, repo, *_ = rig
    svc, provider, assessed, (job,) = queued(rig, create)
    original = repo.mutate

    def commit_late(device, aid, change, **kwargs):
        def delayed(a):
            updated = change(a)
            for j in updated.annotations:
                if j.state == "ready":
                    # The server's commit timestamp arrives after the lease expired.
                    j.finished_at = j.expires_at + timedelta(seconds=1)
            return updated

        return original(device, aid, delayed)

    repo.mutate = commit_late
    svc.work(client.headers["X-Device-ID"], assessed["id"], job)
    assert client.get(path(assessed) + "/" + job).json()["state"] == "failed"
    assert client.get(path(assessed) + "/" + job + "/mask").status_code == 404


def slow_overlay_for_worker_test(mask):
    import time

    time.sleep(10)
    return b"late mask"


def test_cpu_mask_work_is_killed_at_the_operation_deadline(rig, create, monkeypatch):
    import time

    import app.annotations.service as module

    client, *_ = rig
    svc, provider, assessed, (job,) = queued(rig, create)
    monkeypatch.setattr(module, "BUDGET_SECONDS", 0.5)
    monkeypatch.setattr(module, "mask_overlay", slow_overlay_for_worker_test)
    started = time.monotonic()
    svc.work(client.headers["X-Device-ID"], assessed["id"], job)
    assert time.monotonic() - started < 3
    assert client.get(path(assessed) + "/" + job).json()["state"] == "failed"
    assert client.get(path(assessed) + "/" + job + "/mask").status_code == 404


def test_annotation_reads_are_device_scoped(rig, create):
    client, *_ = rig
    svc, provider, assessed, (job,) = queued(rig, create)
    svc.work(client.headers["X-Device-ID"], assessed["id"], job)
    other = {"X-Device-ID": str(uuid4())}
    base = path(assessed) + "/" + job
    for suffix in ("", "/mask"):
        assert client.get(base + suffix, headers=other).status_code == 404
    feedback = client.post(base + "/feedback", headers=other, json={"kind": "wrong_object"})
    assert feedback.status_code == 404
    assert client.post("/internal/annotations/work", json={}).status_code == 401


def test_segmentation_model_must_support_the_sam_3_1_concept_contract():
    import pytest
    from pydantic import ValidationError

    from app.config import Settings

    muse = {"model_provider": "muse", "muse_api_key": "k", "muse_main_model": "main"}
    assert Settings(_env_file=None, muse_segmentation_model="sam-3.1", **muse)
    with pytest.raises(ValidationError):
        Settings(_env_file=None, muse_segmentation_model="sam-2", **muse)
