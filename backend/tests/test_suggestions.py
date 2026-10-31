import pytest
from conftest import assessment_result


def base(assessment):
    return f"/v1/assessments/{assessment['id']}"


SUGGESTIONS = [
    "Start with the cable crossing the walking route.",
    "With a toddler at home, keep low cords out of reach.",
    "Check the room again after rearranging furniture.",
]


def test_findings_come_with_three_saved_suggestions_using_household_context(rig, create):
    client, _, _, provider = rig
    provider.results.append({**assessment_result(), "suggestions": SUGGESTIONS})
    assessment = create(household_context="A 2-year-old")
    result = client.post(base(assessment) + "/analyze").json()
    assert result["suggestions"] == SUGGESTIONS
    assert result["summary"] is None
    assert provider.calls[-1]["context"]["household_context"] == "A 2-year-old"
    # Status changes and reopening never regenerate saved suggestions.
    finding = result["findings"][0]["id"]
    client.patch(base(assessment) + f"/findings/{finding}", json={"status": "resolved"})
    calls = len(provider.calls)
    assert client.get(base(assessment)).json()["suggestions"] == SUGGESTIONS
    assert len(provider.calls) == calls


def test_zero_findings_have_no_suggestions(rig, create):
    client, _, _, provider = rig
    provider.results.append({"title": None, "suggestions": [], "findings": []})
    result = client.post(base(create()) + "/analyze").json()
    assert result["status"] == "complete"
    assert result["findings"] == [] and result["suggestions"] == []


@pytest.mark.parametrize(
    "suggestions",
    [
        SUGGESTIONS[:2],
        [*SUGGESTIONS, "A fourth idea."],
        [SUGGESTIONS[0], "   ", SUGGESTIONS[2]],
        [SUGGESTIONS[0], SUGGESTIONS[0], SUGGESTIONS[2]],
        [SUGGESTIONS[0], "x" * 501, SUGGESTIONS[2]],
        "One. Two. Three.",
    ],
)
def test_invalid_suggestions_fail_through_manual_retry(rig, create, suggestions):
    client, _, _, provider = rig
    provider.results.append({**assessment_result(), "suggestions": suggestions})
    assessment = create()
    assert client.post(base(assessment) + "/analyze").status_code == 502
    failed = client.get(base(assessment)).json()
    assert failed["status"] == "failed" and failed["findings"] == []
    assert failed["suggestions"] is None


def test_suggestions_for_zero_findings_are_rejected(rig, create):
    client, _, _, provider = rig
    provider.results.append({"title": None, "suggestions": SUGGESTIONS, "findings": []})
    assessment = create()
    assert client.post(base(assessment) + "/analyze").status_code == 502


def test_legacy_summary_records_stay_readable_without_suggestions(rig, create):
    client, repo, _, provider = rig
    assessment = create()
    client.post(base(assessment) + "/analyze")

    def legacy(previous):
        previous.summary = "One potential visible hazard."
        previous.suggestions = None
        return previous

    repo.mutate(client.headers["X-Device-ID"], assessment["id"], legacy)
    calls = len(provider.calls)
    loaded = client.get(base(assessment)).json()
    assert loaded["summary"] == "One potential visible hazard."
    assert loaded["suggestions"] is None
    assert len(provider.calls) == calls
