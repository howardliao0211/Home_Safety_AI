"""SAM 3.1 concept segmentation adapter and deterministic candidate choice.

Wire format: https://dev.meta.ai/docs/sam/reading-segmentation
The official parser decodes box-local masks; safety JSON is never used as a mask
format. The main model is never called here, and no method retries a request.
"""

import base64
import io
import json
import math
import re
from dataclasses import dataclass

import httpx
from meta_sam_parser import CompletedOutcome, decode_mask_to_raster, image_segmentation_format
from PIL import Image, ImageDraw

from app.annotations.budget import bounded_cpu, remaining
from app.models.schemas import Region

# Above this, the best overall candidate cannot be claimed; the attempt fails.
MAX_CANDIDATES = 32
# Parser codes for one invalid candidate. Other errors make the response untrustworthy;
# an invalid box also stops the parser reading later candidates on its line.
CANDIDATE_ERRORS = {"invalid_mask_size", "invalid_mask_payload"}


@dataclass
class Candidate:
    id: str
    mask: Image.Image  # Full source size, binary L raster.
    region: Region
    confidence: float | None = None


def image_part(data, content_type="image/jpeg"):
    encoded = base64.b64encode(data).decode("ascii")
    return {"type": "input_image", "image_url": f"data:{content_type};base64,{encoded}"}


def png(image):
    output = io.BytesIO()
    image.save(output, "PNG")
    return output.getvalue()


def highlight(mask):
    """Tint the object's shape and draw a padded box around it.

    Sizes scale with the photo so the box stays visible after the phone shrinks it.
    """
    w, h = mask.size
    side = max(w, h)
    line = max(3, round(side * 0.006))
    rim = max(1, line // 3)
    pad = round(side * 0.02)
    overlay = Image.new("RGBA", mask.size, (255, 122, 0, 0))
    overlay.putalpha(mask.point(lambda value: 102 if value else 0))
    left, top, right, bottom = mask.getbbox()
    box = (
        max(0, left - pad),
        max(0, top - pad),
        min(w - 1, right - 1 + pad),
        min(h - 1, bottom - 1 + pad),
    )
    draw = ImageDraw.Draw(overlay)
    radius = round(line * 2.5)
    draw.rounded_rectangle(box, radius, outline=(60, 25, 0, 255), width=line + 2 * rim)
    inner = (box[0] + rim, box[1] + rim, box[2] - rim, box[3] - rim)
    draw.rounded_rectangle(inner, max(0, radius - rim), outline=(255, 122, 0, 255), width=line)
    return overlay


def decode_candidates(text, size):
    """Decode SAM output in provider order, excluding individually invalid candidates.

    Returns (candidates, excluded_count). Malformed output or source geometry fails.
    """
    w, h = size
    parser = image_segmentation_format().create_parser()
    parser.push(text)
    dimensions = re.findall(r";w=([0-9]+);h=([0-9]+)(?:;c=[^|;]*)?\|>", text)
    if any((int(width), int(height)) != size for width, height in dimensions):
        raise ValueError("Source dimensions mismatch")
    result = parser.finish(CompletedOutcome()).result
    errors = [d for d in result.diagnostics if d.severity == "error"]
    if any(d.code not in CANDIDATE_ERRORS for d in errors):
        raise ValueError("Malformed segmentation")
    masks = [r for r in result.records if r.kind == "mask"]
    if len(masks) + len(errors) > MAX_CANDIDATES:
        raise ValueError("Too many segmentation candidates")
    if any(r.frame is not None for r in masks):
        raise ValueError("Unexpected frame")
    if len({r.object_id for r in masks}) != len(masks):
        raise ValueError("Duplicate candidates")
    candidates = []
    excluded = len(errors)
    for record in masks:
        b = record.bounds
        bounds = (b.left, b.top, b.right, b.bottom)
        if not all(math.isfinite(v) and int(v) == v for v in bounds):
            excluded += 1
            continue
        left, top, right, bottom = map(int, bounds)
        if not (0 <= left < right <= w and 0 <= top < bottom <= h) or (
            record.mask.width,
            record.mask.height,
        ) != (right - left, bottom - top):
            excluded += 1
            continue
        raster = decode_mask_to_raster(record.mask)
        local = Image.frombytes("L", (record.mask.width, record.mask.height), raster).point(
            lambda v: 255 if v else 0
        )
        mask = Image.new("L", size)
        mask.paste(local, (left, top))
        if mask.getbbox() is None:
            excluded += 1
            continue
        candidates.append(
            Candidate(
                record.object_id,
                mask,
                Region(
                    x=left / w,
                    y=top / h,
                    width=(right - left) / w,
                    height=(bottom - top) / h,
                ),
                record.confidence,
            )
        )
    return candidates, excluded


def valid(candidate, size):
    r = candidate.region
    return (
        candidate.mask.size == size
        and candidate.mask.mode == "L"
        and candidate.mask.getbbox() is not None
        and r.x + r.width <= 1
        and r.y + r.height <= 1
    )


def score(candidate):
    c = candidate.confidence
    if isinstance(c, (int, float)) and not isinstance(c, bool) and math.isfinite(c) and 0 <= c <= 1:
        return c
    return None


def choose(candidates, size):
    """Highest valid confidence; scored before unscored; ties and unscored keep provider order.

    Object IDs are never treated as scores. Different instances are never merged.
    """
    usable = [c for c in candidates if valid(c, size)]
    if not usable:
        raise ValueError("No valid segmentation candidate")
    scored = [c for c in usable if score(c) is not None]
    if scored:
        # max() returns the first of equal maxima, preserving provider order.
        best = max(scored, key=score)
        best.confidence = score(best)
        return best
    usable[0].confidence = None
    return usable[0]


class MuseHighlightProvider:
    def __init__(self, settings):
        self.settings = settings

    def client(self, deadline):
        return httpx.AsyncClient(
            base_url="https://api.meta.ai/v1/",
            headers={"Authorization": f"Bearer {self.settings.muse_api_key.get_secret_value()}"},
            timeout=remaining(deadline),
            transport=httpx.AsyncHTTPTransport(retries=0),
        )

    async def segment(self, data, size, prompt, deadline):
        """One SAM request: the image plus one short noun phrase, no box."""
        completed = False
        total = 0
        raw = []
        async with self.client(deadline) as client:
            async with client.stream(
                "POST",
                "responses",
                json={
                    "model": self.settings.muse_segmentation_model,
                    "input": [
                        {
                            "role": "user",
                            "content": [
                                {"type": "input_text", "text": prompt},
                                image_part(data),
                            ],
                        }
                    ],
                    "stream": True,
                    "store": False,
                    "metadata": {"mask_encoding": "one_bit", "include_confidence": "true"},
                },
            ) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    remaining(deadline)
                    total += len(line)
                    if total > 8_000_000:
                        raise ValueError("Oversized segmentation")
                    if not line.startswith("data:"):
                        continue
                    event = json.loads(line[5:].strip())
                    if event["type"] == "response.output_text.delta":
                        raw.append(event["delta"])
                    elif event["type"] == "response.completed":
                        completed = True
                        break
                    elif event["type"] in {"error", "response.failed", "response.incomplete"}:
                        raise ValueError("Segmentation failed")
        if not completed:
            raise ValueError("Incomplete segmentation")
        candidates, excluded = await bounded_cpu(
            decode_candidates, "".join(raw), size, deadline=deadline
        )
        if excluded and not candidates:
            raise ValueError("Every segmentation candidate was invalid")
        return candidates


def mask_overlay(mask):
    return png(highlight(mask))
