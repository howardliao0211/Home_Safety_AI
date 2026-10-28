import asyncio
import hashlib
import io
import logging
import time
from datetime import timedelta

from PIL import Image

from app.annotations.budget import bounded_cpu, remaining
from app.annotations.provider import image_part, mask_overlay
from app.assessments.service import finding_in, require
from app.errors import AppError
from app.models.schemas import Annotation, EvidenceSnapshot, FindingContent, Photo, new_id, now

logger = logging.getLogger(__name__)
ACTIVE = {"queued", "processing"}
BUDGET_SECONDS = 30


def snapshot(assessment, finding):
    """Lazily preserve only evidence actually saved for this content revision."""
    existing = next(
        (s for s in finding.evidence_history if s.revision == finding.content_revision), None
    )
    if existing:
        return existing
    completed = [s for s in finding.submissions if s.status == "complete"]
    saved = EvidenceSnapshot(
        revision=finding.content_revision,
        content=FindingContent.model_validate(
            {k: getattr(finding, k) for k in FindingContent.model_fields}
        ),
        photo_ids=[assessment.photo.id] + [s.photo.id for s in completed if s.photo],
        submission_ids=[s.id for s in completed],
    )
    finding.evidence_history.append(saved)
    return saved


def public_annotation(job):
    return job.model_dump(mode="json", exclude={"lease_id", "expires_at", "mask", "request_id"})


def annotation_in(assessment, finding_id, annotation_id):
    finding_in(assessment, finding_id)
    job = next(
        (j for j in assessment.annotations if j.id == annotation_id and j.finding_id == finding_id),
        None,
    )
    if job is None:
        raise AppError(404, "not_found", "Highlight not found.")
    return job


class AnnotationService:
    def __init__(self, repository, photos, provider, dispatcher=None):
        self.repository, self.photos, self.provider = repository, photos, provider
        self.dispatcher = dispatcher

    def request(self, device, assessment_id, finding_id, body, request_id):
        chosen = []

        def change(previous):
            a = require(previous)
            f = finding_in(a, finding_id)
            if f.content_revision != body.revision:
                raise AppError(
                    409,
                    "stale_revision",
                    "The finding changed. Refresh before requesting a highlight.",
                )
            if a.status != "complete":
                raise AppError(409, "not_assessed", "Finish safety analysis first.")
            if self.provider is None:
                return a
            snapshot(a, f)
            jobs = [
                j
                for j in a.annotations
                if j.finding_id == finding_id and j.revision == body.revision
            ]
            last = jobs[-1] if jobs else None
            if last and (last.state in ACTIVE or not body.retry):
                chosen[:] = [last.id]
                return a
            if len(a.annotations) >= 120:
                raise AppError(
                    409,
                    "annotation_limit",
                    "This assessment has reached its highlight attempt limit.",
                )
            job = Annotation(
                finding_id=finding_id,
                revision=body.revision,
                attempt=len(jobs) + 1,
                request_id=request_id,
            )
            a.annotations.append(job)
            a.annotation_dispatch_pending = True
            chosen[:] = [job.id]
            return a

        a = self.repository.mutate(device, assessment_id, change)
        if not chosen:
            return {
                "state": "unavailable",
                "reason": "MUSE highlighting is unavailable in this configuration.",
                "supported": False,
            }
        # Enqueue failure leaves durable intent for the independent recovery dispatcher.
        self.dispatch(device, assessment_id)
        return public_annotation(next(j for j in a.annotations if j.id == chosen[0]))

    def dispatch(self, device, assessment_id):
        if self.dispatcher:
            try:
                a = self.repository.get(device, assessment_id)
                if a and not a.deleting:
                    job = next((j for j in a.annotations if j.state in ACTIVE), None)
                    if job:
                        self.dispatcher.enqueue(device, assessment_id, job.id)
            except Exception as exc:
                logger.error(
                    "annotation_dispatch_failed assessment_id=%s category=%s",
                    assessment_id,
                    type(exc).__name__,
                )

    def get(self, device, assessment_id, finding_id, annotation_id):
        a = require(self.repository.get(device, assessment_id))
        return annotation_in(a, finding_id, annotation_id)

    def feedback(self, device, assessment_id, finding_id, annotation_id):
        def change(previous):
            a = require(previous)
            job = annotation_in(a, finding_id, annotation_id)
            if job.state not in {"ready", "reported"}:
                raise AppError(409, "not_ready", "Only a published highlight can be reported.")
            job.state, job.feedback = "reported", "wrong_object"
            job.reason = "You reported the wrong object. The highlight stays hidden until you explicitly retry."
            return a

        a = self.repository.mutate(device, assessment_id, change)
        return public_annotation(next(j for j in a.annotations if j.id == annotation_id))

    def mask(self, device, assessment_id, finding_id, annotation_id):
        job = self.get(device, assessment_id, finding_id, annotation_id)
        if job.state != "ready" or not job.mask:
            raise AppError(404, "not_found", "Published highlight not found.")
        return self.photos.get(device, assessment_id, job.mask)

    def work(self, device, assessment_id, annotation_id=None):
        """One durable delivery advances at most one never-started attempt.

        Redelivery only expires a lost attempt; it never repeats provider calls.
        Firestore transactions serialize claims across Cloud Run instances.
        """
        claimed = []
        expired = []
        lease_id = new_id()
        started = time.monotonic()
        deadline = started + BUDGET_SECONDS

        def claim(previous):
            if previous is None or previous.deleting:
                return previous
            a = previous
            claimed.clear()
            expired.clear()
            for j in a.annotations:
                if j.state == "processing":
                    if j.expires_at > now():
                        return a
                    j.state, j.reason = (
                        "failed",
                        "Highlight processing was interrupted. Retry when ready.",
                    )
                    j.finished_at = now()
                    expired.append(j.id)
            for j in a.annotations:
                if j.state != "queued":
                    continue
                if annotation_id and j.id != annotation_id:
                    break
                if finding_in(a, j.finding_id).content_revision != j.revision:
                    j.state, j.reason, j.finished_at = (
                        "failed",
                        "This finding has newer evidence.",
                        now(),
                    )
                    continue
                j.state, j.lease_id = "processing", lease_id
                j.started_at, j.expires_at = now(), now() + timedelta(seconds=BUDGET_SECONDS)
                claimed[:] = [j.id]
                break
            a.annotation_dispatch_pending = any(j.state in ACTIVE for j in a.annotations)
            return a

        a = self.repository.mutate(device, assessment_id, claim, deadline=deadline)
        for expired_id in expired:
            self.cleanup(device, assessment_id, expired_id)
        if not claimed:
            if expired or (a and not any(j.state == "processing" for j in a.annotations)):
                self.dispatch(device, assessment_id)
            return
        job = next(j for j in a.annotations if j.id == claimed[0])
        stage = ["selection"]
        try:
            if self.provider is None:
                raise ValueError("Highlight provider unavailable")
            result = asyncio.run(
                asyncio.wait_for(
                    self._pipeline(device, a, job, deadline, stage), timeout=remaining(deadline)
                )
            )
            stage[0] = "publication"
            state, reason, info, mask_data = result
            remaining(deadline)
            # Reserve the exact asset reference BEFORE writing, so interrupted uploads
            # remain discoverable for deletion and orphan cleanup.
            mask = (
                Photo(
                    id=f"annotation-{job.id}",
                    content_type="image/png",
                    sha256=hashlib.sha256(mask_data).hexdigest(),
                    uploaded=True,
                )
                if mask_data
                else None
            )

            def reserve(previous):
                current = require(previous)
                j = self._publishable(current, job, lease_id)
                for key, value in info.items():
                    setattr(j, key, value)
                j.mask = mask
                return current

            self.repository.mutate(device, assessment_id, reserve, deadline=deadline)
            if mask:
                self.photos.put(device, assessment_id, mask, mask_data, timeout=remaining(deadline))
            remaining(deadline)

            def publish(previous):
                current = require(previous)
                j = self._publishable(current, job, lease_id)
                j.state, j.reason, j.finished_at = state, reason, now()
                current.annotation_dispatch_pending = any(
                    j.state in ACTIVE for j in current.annotations
                )
                return current

            self.repository.mutate(device, assessment_id, publish, deadline=deadline)
            logger.info(
                "annotation_finished annotation_id=%s assessment_id=%s finding_id=%s revision=%s request_id=%s stage=publication duration=%.3f state=%s",
                job.id,
                a.id,
                job.finding_id,
                job.revision,
                job.request_id,
                time.monotonic() - started,
                state,
            )
        except Exception as exc:
            category = (
                "timeout"
                if isinstance(exc, (TimeoutError, asyncio.TimeoutError))
                else type(exc).__name__
            )
            logger.error(
                "annotation_failed annotation_id=%s assessment_id=%s finding_id=%s revision=%s request_id=%s stage=%s duration=%.3f category=%s",
                job.id,
                a.id,
                job.finding_id,
                job.revision,
                job.request_id,
                stage[0],
                time.monotonic() - started,
                category,
            )

            def fail(previous):
                if previous is None:
                    return None
                j = next((j for j in previous.annotations if j.id == job.id), None)
                if j and j.state == "processing" and j.lease_id == lease_id:
                    j.state, j.reason, j.finished_at = (
                        "failed",
                        "Highlight unavailable: processing timed out or failed. Retry when ready.",
                        now(),
                    )
                previous.annotation_dispatch_pending = any(
                    j.state in ACTIVE for j in previous.annotations
                )
                return previous

            self.repository.mutate(device, assessment_id, fail)
        finally:
            # Losing/deletion-racing uploads cannot leave assets behind. A process
            # crash is handled by recover(), using the pre-reserved asset reference.
            self.cleanup(device, assessment_id, job.id)
            self.dispatch(device, assessment_id)

    def _publishable(self, a, job, lease_id):
        j = next(j for j in a.annotations if j.id == job.id)
        if (
            a.deleting
            or j.state != "processing"
            or j.lease_id != lease_id
            or j.expires_at <= now()
            or finding_in(a, job.finding_id).content_revision != job.revision
        ):
            raise AppError(409, "superseded", "Highlight superseded or expired.")
        return j

    async def _pipeline(self, device, a, job, deadline, stage):
        f = finding_in(a, job.finding_id)
        saved = next(s for s in f.evidence_history if s.revision == job.revision)
        candidates = [(a.photo, "original")] + [
            (s.photo, s.kind) for s in f.submissions if s.id in saved.submission_ids and s.photo
        ]
        evidence, images, sources = [], [], {}
        for photo, kind in candidates:
            if not photo.uploaded or photo.id not in saved.photo_ids:
                continue
            try:
                data = await asyncio.to_thread(
                    self.photos.get, device, a.id, photo, timeout=remaining(deadline)
                )
            except Exception:
                return (
                    "unavailable",
                    "A saved evidence photo is missing. Highlighting is unavailable.",
                    {},
                    None,
                )
            if hashlib.sha256(data).hexdigest() != photo.sha256:
                raise ValueError("Source digest mismatch")
            with Image.open(io.BytesIO(data)) as image:
                if image.getexif().get(274, 1) != 1:
                    raise ValueError("Source orientation mismatch")
                size = image.size
            sources[photo.id] = (photo, kind, data, size)
            evidence.append(
                {"photo_id": photo.id, "kind": kind, "width": size[0], "height": size[1]}
            )
            images.extend(
                [
                    {"type": "input_text", "text": f"{kind} photo_id={photo.id}"},
                    image_part(data, photo.content_type),
                ]
            )
        if a.photo.id not in sources:
            return "unavailable", "The original evidence photo is missing.", {}, None
        content = saved.content.model_dump()
        evidence.append(
            {
                "completed_answers": [
                    {"text": s.text, "feedback": s.feedback, "kind": s.kind}
                    for s in f.submissions
                    if s.id in saved.submission_ids
                ]
            }
        )
        selection = await self.provider.select(content, evidence, images, deadline)
        if selection.photo_id is None and selection.target is None and selection.region is None:
            return "unavailable", "No suitable single visible object was identified.", {}, None
        if selection.photo_id not in sources or not selection.target or selection.region is None:
            raise ValueError("Invalid evidence selection")
        photo, kind, data, size = sources[selection.photo_id]
        info = {
            "photo_id": photo.id,
            "photo_kind": kind,
            "image_digest": photo.sha256,
            "width": size[0],
            "height": size[1],
            "target": selection.target,
        }

        def bind_source(previous):
            current = require(previous)
            bound = self._publishable(current, job, job.lease_id)
            for key, value in info.items():
                setattr(bound, key, value)
            return current

        await asyncio.to_thread(
            self.repository.mutate, device, a.id, bind_source, deadline=deadline
        )
        remaining(deadline)
        stage[0] = "segmentation"
        segments = await self.provider.segment(data, size, selection, deadline)
        remaining(deadline)
        if not segments:
            return "unavailable", "No matching visible object was found.", info, None
        # Validate even injected adapter output at the publication boundary.
        for candidate in segments:
            r = candidate.region
            if (
                candidate.mask.size != size
                or candidate.mask.mode != "L"
                or not candidate.mask.getbbox()
                or r.x + r.width > 1
                or r.y + r.height > 1
            ):
                raise ValueError("Invalid candidate geometry")
        stage[0] = "review"
        review = await self.provider.review(data, content, selection, segments, deadline)
        remaining(deadline)
        stage[0] = "validation"
        chosen = [c for c in segments if c.id == review.candidate_id]
        if not review.same_single_object or len(chosen) != 1:
            info["review"] = "rejected"
            return (
                "unavailable",
                "The object highlight could not be confirmed against this evidence.",
                info,
                None,
            )
        info.update(review="approved", region=chosen[0].region)
        return (
            "ready",
            None,
            info,
            await bounded_cpu(mask_overlay, chosen[0].mask, deadline=deadline),
        )

    def cleanup(self, device, assessment_id, annotation_id):
        a = self.repository.get(device, assessment_id)
        j = next((j for j in a.annotations if j.id == annotation_id), None) if a else None
        if (
            j
            and j.state in {"ready", "reported", "processing"}
            and not a.deleting
            and (j.state != "processing" or j.expires_at > now())
        ):
            return
        # Deterministic key also covers a deletion that removed the whole record.
        self.photos.delete(
            device,
            assessment_id,
            Photo(id=f"annotation-{annotation_id}", content_type="image/png", sha256=""),
        )

    def recover(self):
        self.reap_assets()
        for a in self.repository.annotation_pending():
            # Lost attempts expire without ever repeating the model pass.
            self.work(a.device_id, a.id)
            for j in a.annotations:
                if j.state == "failed":
                    self.cleanup(a.device_id, a.id, j.id)

    def reap_assets(self):
        # Also covers a process dying after a deletion-racing upload when its
        # assessment document has already gone. Mask keys never overlap photos.
        for device, assessment_id, annotation_id in self.photos.annotation_assets():
            self.cleanup(device, assessment_id, annotation_id)
