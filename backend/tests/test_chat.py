import threading
import time
from datetime import timedelta
from uuid import uuid4

import pytest
from conftest import Script

from app.errors import ModelError
from app.models.schemas import now


def chat_path(assessment):
    return f"/v1/assessments/{assessment['id']}/findings/{assessment['findings'][0]['id']}/chat"


def send(client, path, text="What should I do?"):
    body = {"id": str(uuid4()), "question": text}
    response = client.post(path + "/turns", json=body)
    assert response.status_code == 201, response.text
    return body["id"]


def retry(client, path, tid, attempt=None):
    return client.post(
        path + f"/turns/{tid}/generate", json={"attempt_id": attempt or str(uuid4())}
    )


def run(client):
    """Deliver every queued attempt once, as Cloud Tasks or the local worker would."""
    chat = client.app.state.chat
    for item in chat.pending():
        chat.work(*item)


def turns(client, path):
    return client.get(path).json()["turns"]


class Recorder:
    def __init__(self, fail=False):
        self.items, self.fail = [], fail

    def enqueue_chat(self, *item):
        self.items.append(item)
        if self.fail:
            raise OSError("queue unavailable")


@pytest.mark.parametrize("status", ["open", "resolved", "dismissed"])
def test_accepting_queues_a_job_before_any_model_call_and_reply_is_advisory(rig, assessed, status):
    client, _, _, provider = rig
    path = chat_path(assessed)
    client.patch(path.removesuffix("/chat"), json={"status": status})
    before = client.get(f"/v1/assessments/{assessed['id']}").json()
    calls = len(provider.calls)
    assert client.get(path).json()["turns"] == []
    body = {"id": str(uuid4()), "question": "How can I keep this walkway clear?"}
    first = client.post(path + "/turns", json=body)
    assert first.status_code == 201, first.text
    queued = first.json()["turns"][0]
    assert queued["status"] == "queued" and queued["partial"] == "" and queued["version"] == 1
    assert len(provider.calls) == calls  # Acceptance never waits for the model.
    assert client.post(path + "/turns", json=body).json() == first.json()
    assert client.post(path + "/turns", json={**body, "question": "Different"}).status_code == 409
    assert not {"attempt_ids", "execution", "expires_at", "queued_until"}.intersection(queued)
    provider.results.append({"answer": "Keep cables away from the walking route if safe."})
    run(client)
    run(client)  # Nothing left to deliver.
    done = turns(client, path)[0]
    assert done["status"] == "complete" and done["answer"].startswith("Keep cables")
    assert done["partial"] == "" and done["version"] > queued["version"]
    assert len(provider.calls) == calls + 1
    assert client.get(f"/v1/assessments/{assessed['id']}").json() == before


def test_partial_text_is_published_before_the_terminal_event(rig, assessed):
    client, _, _, provider = rig
    path = chat_path(assessed)
    tid = send(client, path)
    first_out, release = threading.Event(), threading.Event()

    def pause():
        first_out.set()
        assert release.wait(5)

    provider.results.append(Script(["Keep the ", "route ", "clear."], gates={1: pause}))
    worker = threading.Thread(target=run, args=(client,))
    worker.start()
    assert first_out.wait(5)
    deadline = time.monotonic() + 0.5
    while not (during := turns(client, path)[0])["partial"] and time.monotonic() < deadline:
        time.sleep(0.01)
    assert during["status"] == "running" and during["partial"] == "Keep the "
    assert during["answer"] is None
    release.set()
    worker.join(5)
    after = turns(client, path)[0]
    assert after["status"] == "complete" and after["answer"] == "Keep the route clear."
    assert after["version"] > during["version"]
    assert after["id"] == tid


def test_text_received_before_a_provider_pause_is_published_promptly(rig, assessed):
    client, _, _, provider = rig
    path = chat_path(assessed)
    send(client, path)
    paused, release = threading.Event(), threading.Event()

    def pause():
        paused.set()
        assert release.wait(5)

    # The provider goes quiet after three quick fragments; none may wait for a fourth.
    provider.results.append(Script(["Keep ", "the ", "route ", "clear."], gates={3: pause}))
    worker = threading.Thread(target=run, args=(client,))
    worker.start()
    try:
        assert paused.wait(5)
        received = time.monotonic()
        while turns(client, path)[0]["partial"] != "Keep the route ":
            assert time.monotonic() - received < 0.5, turns(client, path)[0]["partial"]
            time.sleep(0.01)
    finally:
        release.set()
        worker.join(5)
    assert turns(client, path)[0]["answer"] == "Keep the route clear."


def test_partials_are_batched_on_a_bounded_cadence(rig, assessed):
    client, repo, _, provider = rig
    path = chat_path(assessed)
    send(client, path)
    writes = []
    original = repo.mutate

    def counting(*args, **kwargs):
        writes.append(1)
        return original(*args, **kwargs)

    repo.mutate = counting
    provider.results.append(Script([f"word{i} " for i in range(200)]))
    run(client)
    # Claim, first partial and completion; not one write per fragment.
    assert len(writes) <= 4
    assert turns(client, path)[0]["answer"].startswith("word0 word1")


def test_failure_after_partial_is_incomplete_and_retry_replaces_it(rig, assessed):
    client, _, _, provider = rig
    path = chat_path(assessed)
    tid = send(client, path, "How do I reduce trips?")
    provider.results.append(Script(["Start by ", "clearing"], error=ModelError("transport")))
    run(client)
    failed = turns(client, path)[0]
    assert failed["status"] == "failed" and failed["partial"] == "Start by clearing"
    assert failed["answer"] is None and failed["error"]
    assert failed["error_code"] == "transport"
    # Another question waits for the unfinished turn.
    blocked = client.post(path + "/turns", json={"id": str(uuid4()), "question": "Next?"})
    assert blocked.status_code == 409
    attempt = str(uuid4())
    queued = retry(client, path, tid, attempt).json()["turns"][0]
    assert queued["status"] == "queued" and queued["partial"] == ""
    assert retry(client, path, tid, attempt).json()["turns"][0]["version"] == queued["version"]
    provider.results.append({"answer": "A fresh, complete answer."})
    run(client)
    done = turns(client, path)
    assert len(done) == 1 and done[0]["answer"] == "A fresh, complete answer."
    # Only completed replies enter later context; the failed partial never does.
    send(client, path, "And at night?")
    run(client)
    assert provider.calls[-1]["context"]["previous_chat"] == [
        {"user": "How do I reduce trips?", "assistant": "A fresh, complete answer."}
    ]


@pytest.mark.parametrize(
    "category", ["refused", "truncated", "early_eof", "provider_failed", "timeout"]
)
def test_unsuccessful_terminal_states_are_never_complete(rig, assessed, category):
    client, _, _, provider = rig
    path = chat_path(assessed)
    tid = send(client, path)
    provider.results.append(Script(["Partial words"], error=ModelError(category)))
    run(client)
    turn = turns(client, path)[0]
    assert turn["status"] == "failed" and turn["error_code"] == category
    assert turn["partial"] == "Partial words" and turn["answer"] is None
    assert retry(client, path, tid).json()["turns"][0]["status"] == "queued"


def test_blank_or_overlong_answers_fail(rig, assessed):
    client, _, _, provider = rig
    path = chat_path(assessed)
    tid = send(client, path)
    provider.results.append(Script(["  ", "\n"]))
    run(client)
    assert turns(client, path)[0]["error_code"] == "invalid_response"
    retry(client, path, tid)
    provider.results.append(Script(["x" * 2000, "y" * 1500]))
    run(client)
    turn = turns(client, path)[0]
    assert turn["error_code"] == "too_long" and len(turn["partial"]) <= 3000


def test_context_limit_is_non_transient(rig, assessed):
    client, _, _, provider = rig
    path = chat_path(assessed)
    tid = send(client, path)
    provider.results.append(ModelError("context_limit"))
    run(client)
    result = client.get(path).json()
    assert result["blocked_reason"] and result["turns"][0]["error_code"] == "context_limit"
    calls = len(provider.calls)
    assert retry(client, path, tid).status_code == 409
    run(client)
    assert len(provider.calls) == calls


def test_duplicate_and_stale_deliveries_never_repeat_a_claimed_attempt(rig, assessed):
    client, _, _, provider = rig
    path = chat_path(assessed)
    send(client, path)
    chat = client.app.state.chat
    (item,) = chat.pending()
    calls = len(provider.calls)

    def redeliver():
        chat.work(*item)  # Duplicate delivery while the stream is running.

    provider.on_call = redeliver
    chat.work(*item)
    provider.on_call = None
    chat.work(*item)  # Lost-response redelivery after completion.
    chat.work(*item[:4], str(uuid4()))  # Unknown attempt.
    assert len(provider.calls) == calls + 1
    assert turns(client, path)[0]["status"] == "complete"


def test_expired_claims_and_queues_fail_without_another_model_call(rig, assessed):
    client, repo, _, provider = rig
    path = chat_path(assessed)
    tid = send(client, path)
    device = client.headers["X-Device-ID"]

    def interrupt(a):
        t = a.findings[0].chat[0]
        t.status, t.execution = "running", "lost-worker"
        t.expires_at = now() - timedelta(seconds=1)
        t.partial = "Half an"
        return a

    repo.mutate(device, assessed["id"], interrupt)
    calls = len(provider.calls)
    # Observation reports the expiry without writing; recovery persists it.
    assert turns(client, path)[0]["status"] == "failed"
    client.app.state.chat.recover()
    stored = repo.get(device, assessed["id"])
    turn = stored.findings[0].chat[0]
    assert turn.status == "failed" and turn.error_code == "interrupted"
    assert turn.partial == "Half an" and not stored.chat_dispatch_pending
    run(client)
    assert len(provider.calls) == calls

    retry(client, path, tid)

    def stale_queue(a):
        a.findings[0].chat[0].queued_until = now() - timedelta(seconds=1)
        return a

    repo.mutate(device, assessed["id"], stale_queue)
    client.app.state.chat.recover()
    assert turns(client, path)[0]["error_code"] == "not_started"
    assert len(provider.calls) == calls


def test_dispatch_intent_survives_enqueue_failure_and_recovery_redelivers(rig, assessed):
    client, _, _, provider = rig
    chat = client.app.state.chat
    chat.dispatcher = Recorder(fail=True)
    path = chat_path(assessed)
    tid = send(client, path)
    assert len(chat.dispatcher.items) == 1
    chat.dispatcher = Recorder()
    calls = len(provider.calls)
    chat.recover()
    (item,) = chat.dispatcher.items
    assert item[2:4] == (assessed["findings"][0]["id"], tid)
    assert len(provider.calls) == calls  # Recovery delivers; it never generates.
    chat.work(*item)
    chat.recover()
    assert len(chat.dispatcher.items) == 1


def test_legacy_turns_stay_readable_and_unstarted_ones_continue_explicitly(rig, assessed):
    from app.models.schemas import ChatTurn

    client, repo, _, provider = rig
    path = chat_path(assessed)

    def legacy(a):
        a.findings[0].chat = [
            ChatTurn(id=str(uuid4()), question="Old", answer="Old answer", status="complete"),
            ChatTurn(id=str(uuid4()), question="Never started"),
        ]
        return a

    stored = repo.mutate(client.headers["X-Device-ID"], assessed["id"], legacy)
    calls = len(provider.calls)
    assert [t["status"] for t in turns(client, path)] == ["complete", "ready"]
    run(client)
    assert len(provider.calls) == calls  # Opening never generates.
    pending = stored.findings[0].chat[1].id
    assert retry(client, path, pending).json()["turns"][1]["status"] == "queued"
    run(client)
    assert turns(client, path)[1]["status"] == "complete"


def test_concurrent_status_changes_survive_partial_writes(rig, assessed):
    client, _, _, provider = rig
    path = chat_path(assessed)
    send(client, path)
    finding = path.removesuffix("/chat")

    def resolve():
        assert client.patch(finding, json={"status": "resolved"}).status_code == 200

    provider.results.append(Script(["One ", "two."], gates={1: resolve}))
    run(client)
    saved = client.get(f"/v1/assessments/{assessed['id']}").json()["findings"][0]
    assert saved["status"] == "resolved"
    assert turns(client, path)[0]["answer"] == "One two."


def test_chat_is_owner_scoped_and_deletion_cannot_be_resurrected(rig, assessed):
    client, repo, _, provider = rig
    path = chat_path(assessed)
    tid = send(client, path)
    owner = client.headers["Authorization"]
    client.headers["Authorization"] = "Bearer " + str(uuid4())
    assert client.get(path).status_code == 404
    other = client.post(path + "/turns", json={"id": str(uuid4()), "question": "Other account"})
    assert other.status_code == 404
    assert retry(client, path, tid).status_code == 404
    client.headers["Authorization"] = owner

    def delete():
        assert client.delete(f"/v1/assessments/{assessed['id']}").status_code == 204

    provider.results.append(Script(["Must ", "never ", "resurrect."], gates={1: delete}))
    run(client)
    assert client.get(path).status_code == 404
    assert repo.get(client.headers["X-Device-ID"], assessed["id"]) is None


def test_blank_long_and_full_context_do_not_accept_questions(rig, assessed):
    client, repo, _, provider = rig
    path = chat_path(assessed)
    for text in ["  \n ", "x" * 2001]:
        response = client.post(path + "/turns", json={"id": str(uuid4()), "question": text})
        assert response.status_code == 422

    def full(a):
        a.household_context = "x" * 25000
        return a

    repo.mutate(client.headers["X-Device-ID"], assessed["id"], full)
    calls = len(provider.calls)
    assert client.get(path).json()["blocked_reason"]
    response = client.post(path + "/turns", json={"id": str(uuid4()), "question": "A question"})
    assert response.status_code == 409
    assert len(provider.calls) == calls


def test_another_finding_history_is_excluded(rig, assessed):
    from conftest import content

    from app.models.schemas import Finding

    client, repo, _, provider = rig

    def other(a):
        a.findings.append(Finding(**content()))
        return a

    changed = repo.mutate(client.headers["X-Device-ID"], assessed["id"], other)
    first = chat_path(assessed)
    send(client, first, "First question")
    run(client)
    second = f"/v1/assessments/{assessed['id']}/findings/{changed.findings[1].id}/chat"
    send(client, second)
    run(client)
    assert provider.calls[-1]["context"]["previous_chat"] == []


def test_context_includes_saved_history_household_and_original_photo(rig, assessed):
    from conftest import content

    client, _, _, provider = rig
    path = chat_path(assessed)
    fid_path = path.removesuffix("/chat")
    sid = str(uuid4())
    client.post(
        fid_path + "/submissions",
        data={"submission_id": sid, "kind": "follow-up", "text": "Used at night"},
    )
    provider.results.append({"finding": content(), "feedback": "Night use adds context."})
    client.post(fid_path + f"/submissions/{sid}/analyze")
    provider.results.append({"answer": "Keep the route clear."})
    send(client, path, "How can I reduce trips?")
    run(client)
    client.patch(fid_path, json={"status": "resolved"})
    send(client, path, "Does that also help at night?")
    run(client)
    call = provider.calls[-1]
    assert call["context"]["finding"]["status"] == "resolved"
    assert call["context"]["profiles"] == ["Older adult", "Baby", "Pet"]
    assert "household_context" in call["context"]
    assert call["context"]["previous_chat"] == [
        {"user": "How can I reduce trips?", "assistant": "Keep the route clear."}
    ]
    assert call["context"]["historical_discussion"][0]["user_text"] == "Used at night"
    assert call["context"]["current_question"] == "Does that also help at night?"
    assert len(call["images"]) == 1 and call["max_output_tokens"] > 0


def test_last_accepted_question_can_still_retry_at_turn_limit(rig, assessed):
    client, _, _, provider = rig
    path = chat_path(assessed)
    for _ in range(11):
        send(client, path)
        run(client)
    tid = send(client, path, "Last question")
    provider.results.append(ModelError("timeout"))
    run(client)
    result = client.get(path).json()
    assert result["blocked_reason"] and result["retry_blocked_reason"] is None
    retry(client, path, tid)
    run(client)
    assert turns(client, path)[-1]["status"] == "complete"
