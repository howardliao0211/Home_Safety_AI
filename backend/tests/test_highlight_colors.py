import io

import pytest
from PIL import Image
from test_annotations import analyze, candidate, enabled, findings, path

from app.annotations.provider import highlight, recolor

COLORS = {"High": (220, 38, 38), "Medium": (250, 204, 21), "Low": (22, 163, 74)}


def pixels(data):
    return Image.open(io.BytesIO(data)).convert("RGBA")


def legacy_orange():
    """A mask stored before severity colors: orange tint with a dark rim."""
    mask = candidate("1", (100, 60)).mask
    output = io.BytesIO()
    highlight(mask).save(output, "PNG")
    return output.getvalue(), mask


@pytest.mark.parametrize("severity", ["High", "Medium", "Low"])
def test_stored_orange_masks_are_tinted_by_severity_with_geometry_preserved(severity):
    data, mask = legacy_orange()
    before, after = pixels(data), pixels(recolor(data, severity))
    assert after.size == before.size
    assert after.getchannel("A").tobytes() == before.getchannel("A").tobytes()
    inside = after.getpixel((20, 20))  # Translucent fill inside the object.
    assert inside[:3] == COLORS[severity] and 0 < inside[3] < 255
    assert after.getpixel((95, 2))[3] == 0  # Outside stays transparent.
    # The darker rim keeps the outline distinguishable from the fill.
    rims = {
        after.getpixel((x, y))[:3]
        for x in range(100)
        for y in range(60)
        if after.getpixel((x, y))[3] == 255
    }
    assert COLORS[severity] in rims and len(rims) == 2


def test_served_masks_use_the_findings_severity_without_new_segmentation(rig, create):
    client, *_ = rig
    svc, provider = enabled(rig)
    result = findings("tall cabinet", "power cable", "small toys")
    for item, severity in zip(result["findings"], ("High", "Medium", "Low"), strict=True):
        item["severity"] = severity
    assessed = analyze(rig, create, result)
    device = client.headers["X-Device-ID"]
    for finding in assessed["findings"]:
        svc.work(device, assessed["id"], finding["annotation"]["id"])
    calls = list(provider.calls)
    for index, finding in enumerate(assessed["findings"]):
        url = path(assessed, index) + "/" + finding["annotation"]["id"] + "/mask"
        image = pixels(client.get(url).content)
        assert image.getpixel((20, 20))[:3] == COLORS[finding["severity"]]
    assert provider.calls == calls


def test_historical_highlight_keeps_its_revisions_severity(rig, create):
    from uuid import uuid4

    from conftest import content

    client, _, _, safety = rig
    svc, _ = enabled(rig)
    assessed = analyze(rig, create, findings("power cable"))  # Medium.
    job = assessed["findings"][0]["annotation"]["id"]
    svc.work(client.headers["X-Device-ID"], assessed["id"], job)
    finding_url = path(assessed).removesuffix("/annotations")
    sid = str(uuid4())
    client.post(
        finding_url + "/submissions",
        data={"submission_id": sid, "kind": "follow-up", "text": "Used at night"},
    )
    safety.results.append({"finding": {**content(), "severity": "High"}, "feedback": "Updated."})
    revised = client.post(finding_url + f"/submissions/{sid}/analyze").json()
    assert revised["findings"][0]["severity"] == "High"
    image = pixels(client.get(path(assessed) + "/" + job + "/mask").content)
    assert image.getpixel((20, 20))[:3] == COLORS["Medium"]
