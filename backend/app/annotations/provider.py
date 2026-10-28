"""MUSE selection/review and a separate SAM streaming mask adapter.

Wire format: https://dev.meta.ai/docs/sam/reading-segmentation
The official parser decodes box-local base85 masks; safety JSON is never used
as a mask format. No adapter method retries a request.
"""

import base64
import io
import json
import math
import re
import time
from dataclasses import dataclass

import httpx
from meta_sam_parser import CompletedOutcome, decode_mask_to_raster, image_segmentation_format
from PIL import Image, ImageChops, ImageDraw, ImageFilter

from app.models.schemas import Region, StrictModel


class Selection(StrictModel):
    photo_id: str | None
    target: str | None
    # Spatial guidance disambiguates instances. No object is represented by null.
    region: Region | None


class Review(StrictModel):
    candidate_id: str | None
    same_single_object: bool


@dataclass
class Candidate:
    id: str
    mask: Image.Image  # Full source size, binary L raster.
    region: Region


def remaining(deadline):
    seconds = deadline - time.monotonic()
    if seconds <= 0:
        raise TimeoutError()
    return seconds


def image_part(data, content_type="image/jpeg"):
    encoded = base64.b64encode(data).decode("ascii")
    return {"type": "input_image", "image_url": f"data:{content_type};base64,{encoded}"}


def png(image):
    output = io.BytesIO()
    image.save(output, "PNG")
    return output.getvalue()


def highlight(mask):
    edge = ImageChops.subtract(
        mask.filter(ImageFilter.MaxFilter(5)), mask.filter(ImageFilter.MinFilter(5))
    )
    overlay = Image.new("RGBA", mask.size, (255, 170, 0, 0))
    overlay.putalpha(mask.point(lambda value: 85 if value else 0))
    outline = Image.new("RGBA", mask.size, (115, 45, 0, 255))
    overlay.paste(outline, (0, 0), edge)
    return overlay


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

    async def structured(self, instructions, context, images, schema, deadline):
        async with self.client(deadline) as client:
            response = await client.post(
                "responses",
                json={
                    "model": self.settings.muse_main_model,
                    "instructions": instructions,
                    "input": [
                        {
                            "role": "user",
                            "content": [
                                {"type": "input_text", "text": json.dumps(context)},
                                *images,
                            ],
                        }
                    ],
                    "text": {
                        "format": {
                            "type": "json_schema",
                            "name": schema.__name__,
                            "schema": schema.model_json_schema(),
                            "strict": True,
                        }
                    },
                    "max_output_tokens": 1500,
                    "stream": False,
                    "store": False,
                },
            )
            response.raise_for_status()
            body = response.json()
            if body["status"] != "completed":
                raise ValueError("Incomplete structured response")
            blocks = [
                block
                for item in body["output"]
                if item["type"] == "message"
                for block in item["content"]
            ]
            if not blocks or any(block["type"] != "output_text" for block in blocks):
                raise ValueError("Invalid structured response")
            return schema.model_validate_json("".join(block["text"] for block in blocks))

    async def select(self, content, evidence, images, deadline):
        return await self.structured(
            "Select exactly one visible main object supported by this finding's evidence. "
            "Prefer the object the recommended action concerns. Choose only a relevant listed "
            "photo; distinguish repeated objects with a tight normalized bounding region. "
            "Return all null fields if no suitable single visible object exists. "
            "Do not infer invisible changes, anchoring, resolution, or safety verification.",
            {"finding": content, "evidence": evidence},
            images,
            Selection,
            deadline,
        )

    async def segment(self, data, size, selection, deadline):
        w, h = size
        r = selection.region
        if r.x + r.width > 1 or r.y + r.height > 1:
            raise ValueError("Invalid selection geometry")
        x1, y1 = int(r.x * w), int(r.y * h)
        x2, y2 = (
            min(w - 1, math.ceil((r.x + r.width) * w) - 1),
            min(h - 1, math.ceil((r.y + r.height) * h) - 1),
        )
        prompt = f"<0f>1<|box;x1={x1};y1={y1};x2={x2};y2={y2};w={w};h={h}|>"
        parser = image_segmentation_format().create_parser()
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
                    "metadata": {"mask_encoding": "one_bit"},
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
                        parser.push(event["delta"])
                    elif event["type"] == "response.completed":
                        completed = True
                        break
                    elif event["type"] in {"error", "response.failed", "response.incomplete"}:
                        raise ValueError("Segmentation failed")
        if not completed:
            raise ValueError("Incomplete segmentation")
        dimensions = re.findall(r";w=([0-9]+);h=([0-9]+)(?:;c=[0-9.]+)?\|>", "".join(raw))
        if any((int(width), int(height)) != size for width, height in dimensions):
            raise ValueError("Source dimensions mismatch")
        result = parser.finish(CompletedOutcome()).result
        if result.diagnostics:
            raise ValueError("Malformed segmentation")
        candidates = []
        for record in result.records:
            if record.kind != "mask":
                continue
            if len(candidates) >= 12 or record.frame is not None:
                raise ValueError("Invalid candidate count or frame")
            b = record.bounds
            bounds = (b.left, b.top, b.right, b.bottom)
            if not all(math.isfinite(v) and int(v) == v for v in bounds):
                raise ValueError("Invalid mask geometry")
            left, top, right, bottom = map(int, bounds)
            if not (0 <= left < right <= w and 0 <= top < bottom <= h):
                raise ValueError("Out of bounds mask")
            if (record.mask.width, record.mask.height) != (right - left, bottom - top):
                raise ValueError("Mask size mismatch")
            raster = decode_mask_to_raster(record.mask)
            local = Image.frombytes("L", (record.mask.width, record.mask.height), raster).point(
                lambda v: 255 if v else 0
            )
            mask = Image.new("L", size)
            mask.paste(local, (left, top))
            if mask.getbbox() is None:
                raise ValueError("Empty mask")
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
                )
            )
        if len({c.id for c in candidates}) != len(candidates):
            raise ValueError("Duplicate candidates")
        return candidates

    async def review(self, data, content, selection, candidates, deadline):
        images = [image_part(data)]
        for candidate in candidates:
            original = Image.open(io.BytesIO(data)).convert("RGBA")
            original = Image.alpha_composite(original, highlight(candidate.mask))
            ImageDraw.Draw(original).text(
                (10, 10),
                f"Candidate {candidate.id}",
                fill="black",
                stroke_width=2,
                stroke_fill="white",
            )
            images.extend(
                [
                    {"type": "input_text", "text": f"Candidate {candidate.id}"},
                    image_part(png(original), "image/png"),
                ]
            )
        return await self.structured(
            "Review localisation only. Compare the original with the labelled candidate overlays. "
            "Approve exactly one candidate only if all visible mask components belong to the SAME "
            "single object instance intended by the finding and selection. Reject unrelated, "
            "ambiguous, empty, or multiple-object masks. Return candidate_id null and "
            "same_single_object false on rejection. Do not revise the finding or verify safety.",
            {"finding": content, "selection": selection.model_dump()},
            images,
            Review,
            deadline,
        )
