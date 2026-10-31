import base64
import json
from uuid import uuid4

import pytest
from conftest import assessment_result


def test_assessment_title_is_saved_and_history_is_lightweight(rig, create):
    client, _, _, provider = rig
    title = "A quiet living room with a reading corner beside the window"
    provider.results.append({**assessment_result(), "title": title})
    assessment = create()
    path = f"/v1/assessments/{assessment['id']}"
    result = client.post(path + "/analyze")
    assert result.status_code == 200, result.text
    assert client.get(path).json()["title"] == title
    history = client.get("/v1/assessments")
    assert history.status_code == 200, history.text
    item = history.json()["items"][0]
    assert item["title"] == title and item["open_count"] == 1
    assert item["photo"]["id"] == assessment["photo"]["id"]
    assert "findings" not in item and "owner_uid" not in item
    assert len(provider.calls) == 1
    fid = result.json()["findings"][0]["id"]
    client.patch(path + f"/findings/{fid}", json={"status": "resolved"})
    assert client.get(path).json()["title"] == title
    assert client.get("/v1/assessments").json()["items"][0]["open_count"] == 0


def test_history_paginates_ties_excludes_deletions_and_scopes_accounts(rig, create):
    client, repo, _, provider = rig
    owner = client.headers["Authorization"].removeprefix("Bearer ")
    records = [create() for _ in range(5)]
    timestamp = repo.get(owner, records[0]["id"]).created_at

    def same_date(a):
        a.created_at = timestamp
        return a

    for record in records:
        repo.mutate(owner, record["id"], same_date)
    hidden = records.pop()

    def deleting(a):
        a.deleting = True
        return a

    repo.mutate(owner, hidden["id"], deleting)
    first = client.get("/v1/assessments?limit=2").json()
    cursor = first["next_cursor"]
    second = client.get("/v1/assessments", params={"limit": 2, "cursor": cursor}).json()
    ids = [a["id"] for a in first["items"] + second["items"]]
    assert ids == sorted((a["id"] for a in records), reverse=True)
    assert second["next_cursor"] is None
    assert all(a["open_count"] is None for a in first["items"])
    client.headers["Authorization"] = "Bearer " + str(uuid4())
    assert client.get("/v1/assessments").json() == {"items": [], "next_cursor": None}
    assert client.get("/v1/assessments", params={"cursor": cursor}).status_code == 422
    assert client.get(f"/v1/assessments/{ids[0]}").status_code == 404
    assert not provider.calls


@pytest.mark.parametrize("title", [None, "", "   "])
def test_legacy_and_blank_titles_do_not_fail_analysis(rig, create, title):
    client, _, _, provider = rig
    result = assessment_result()
    if title is not None:
        result["title"] = title
    provider.results.append(result)
    assessment = create()
    response = client.post(f"/v1/assessments/{assessment['id']}/analyze")
    assert response.status_code == 200, response.text
    assert response.json()["title"] == title


def test_history_rejects_bad_limits_and_cursors(rig):
    client, *_ = rig
    from app.auth import owner_key

    owner = client.headers["Authorization"].removeprefix("Bearer ")
    malformed = base64.urlsafe_b64encode(
        json.dumps([owner_key(owner), "2026-10-31T00:00:00+00:00", 12]).encode()
    ).decode()
    for params in ({"limit": 0}, {"limit": 101}, {"cursor": "invalid"}, {"cursor": malformed}):
        assert client.get("/v1/assessments", params=params).status_code == 422
    del client.headers["Authorization"]
    assert client.get("/v1/assessments").status_code == 401
