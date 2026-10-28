import asyncio
import hashlib
import io
import logging
import re
import time
from datetime import timedelta

from PIL import Image

from app.annotations.budget import bounded_cpu, remaining
from app.annotations.provider import choose, mask_overlay
from app.assessments.service import finding_in, require
from app.errors import AppError
from app.models.schemas import Annotation, EvidenceSnapshot, FindingContent, Photo, new_id, now

logger = logging.getLogger(__name__)
ACTIVE = {"queued", "processing"}
BUDGET_SECONDS = 30
PROMPT_LIMIT = 200
UNSUPPORTED = "MUSE highlighting is unavailable in this configuration."
NO_OBJECT = "No single visible object was identified to highlight for this finding."
UNUSABLE = "The highlight description for this finding was unusable, so no highlight was made."


def segmentation_prompt(raw):
    """Normalize the assessment's SAM noun phrase; return (prompt, unavailable reason)."""
    if raw is None:
        return None, NO_OBJECT
    text = " ".join(raw.split())
    # One concept only; list separators and wire-format characters are rejected.
    if not text or len(text) > PROMPT_LIMIT or re.search(r"[,;+<>|\x00-\x1f]", text):
        return None, UNUSABLE
    return text, None


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
    result = job.model_dump(
        mode="json", exclude={"lease_id", "expires_at", "mask", "request_id", "prompt"}
    )
    # Legacy attempts have no saved prompt, and retry never asks the main model again.
    result["retryable"] = job.prompt is not None
    return result


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

    def seed(self, assessment, proposed, request_id):
        """Create initial attempts inside the assessment-completion commit.

        Only initial findings are segmented, always on the initial photo.
        """
        for finding, item in zip(assessment.findings, proposed, strict=True):
            if any(j.finding_id == finding.id for j in assessment.annotations):
                continue
            snapshot(assessment, finding)
            prompt, reason = segmentation_prompt(item.segmentation_prompt)
            job = Annotation(
                finding_id=finding.id,
                revision=finding.content_revision,
                attempt=1,
                request_id=request_id,
                prompt=prompt,
                photo_id=assessment.photo.id,
                photo_kind="original",
                image_digest=assessment.photo.sha256,
            )
            if reason or self.provider is None:
                job.state, job.reason, job.finished_at = "unavailable", reason or UNSUPPORTED, now()
            assessment.annotations.append(job)
        assessment.annotation_dispatch_pending = any(
            j.state in ACTIVE for j in assessment.annotations
        )

    def request(self, device, assessment_id, finding_id, body, request_id):
        """Return the current attempt, or explicitly retry it with the saved prompt."""
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
            jobs = [
                j
                for j in a.annotations
                if j.finding_id == finding_id and j.revision == body.revision
            ]
            last = jobs[-1] if jobs else None
            if last and (last.state in ACTIVE or not body.retry):
                chosen[:] = [last.id]
                return a
            if last is None:
                raise AppError(
                    409,
                    "retry_unavailable",
                    "Highlights are generated only for initial assessment findings.",
                )
            if last.prompt is None:
                raise AppError(
                    409,
                    "retry_unavailable",
                    "This highlight cannot be retried because no highlight description was saved.",
                )
            if self.provider is None:
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
                prompt=last.prompt,
                photo_id=a.photo.id,
                photo_kind="original",
                image_digest=a.photo.sha256,
            )
            a.annotations.append(job)
            a.annotation_dispatch_pending = True
            chosen[:] = [job.id]
            return a

        a = self.repository.mutate(device, assessment_id, change)
        if not chosen:
            return {"state": "unavailable", "reason": UNSUPPORTED, "supported": False}
        job = next(j for j in a.annotations if j.id == chosen[0])
        if job.state == "queued":
            # Enqueue failure leaves durable intent for the independent recovery dispatcher.
            self.dispatch(device, assessment_id, job.id)
        return public_annotation(job)

    def dispatch(self, device, assessment_id, annotation_id=None):
        """Enqueue every active attempt independently; claims make redelivery safe."""
        if not self.dispatcher:
            return
        try:
            a = self.repository.get(device, assessment_id)
        except Exception as exc:
            logger.error(
                "annotation_dispatch_failed assessment_id=%s category=%s",
                assessment_id,
                type(exc).__name__,
            )
            return
        if not a or a.deleting:
            return
        for job in a.annotations:
            if job.state not in ACTIVE or (annotation_id and job.id != annotation_id):
                continue
            try:
                self.dispatcher.enqueue(device, assessment_id, job.id)
            except Exception as exc:
                logger.error(
                    "annotation_dispatch_failed assessment_id=%s finding_id=%s annotation_id=%s "
                    "request_id=%s category=%s",
                    assessment_id,
                    job.finding_id,
                    job.id,
                    job.request_id,
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

    def work(self, device, assessment_id, annotation_id):
        """One durable delivery advances one never-started attempt.

        Sibling attempts are claimed independently, so a slow finding never blocks
        another. Redelivery only expires a lost attempt; it never repeats provider
        calls. Firestore preconditions serialize each claim across instances.
        """
        claimed = []
        expired = []
        lease_id = new_id()
        started = time.monotonic()
        deadline = started + BUDGET_SECONDS

        def claim(previous):
            claimed.clear()
            expired.clear()
            if previous is None or previous.deleting:
                return previous
            a = previous
            j = next((j for j in a.annotations if j.id == annotation_id), None)
            if j and j.state == "processing" and j.expires_at <= now():
                j.state, j.reason, j.finished_at = (
                    "failed",
                    "Highlight processing was interrupted. Retry when ready.",
                    now(),
                )
                expired.append(j.id)
            elif j and j.state == "queued":
                if finding_in(a, j.finding_id).content_revision != j.revision:
                    j.state, j.reason, j.finished_at = (
                        "failed",
                        "This finding has newer evidence.",
                        now(),
                    )
                elif not j.prompt:
                    j.state, j.reason, j.finished_at = "unavailable", UNUSABLE, now()
                else:
                    j.state, j.lease_id = "processing", lease_id
                    j.started_at, j.expires_at = now(), now() + timedelta(seconds=BUDGET_SECONDS)
                    claimed.append(j.id)
            a.annotation_dispatch_pending = any(j.state in ACTIVE for j in a.annotations)
            return a

        try:
            a = self.repository.mutate(device, assessment_id, claim, deadline=deadline)
        except AppError as exc:
            if exc.code == "account_deleting":
                return
            raise
        for expired_id in expired:
            self.cleanup(device, assessment_id, expired_id)
        if not claimed:
            return
        job = next(j for j in a.annotations if j.id == claimed[0])
        stage = ["source"]
        timings = {}
        try:
            if self.provider is None:
                raise ValueError("Highlight provider unavailable")
            result = asyncio.run(
                asyncio.wait_for(
                    self._pipeline(device, a, job, deadline, stage, timings),
                    timeout=remaining(deadline),
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
                "annotation_finished annotation_id=%s assessment_id=%s finding_id=%s revision=%s request_id=%s stage=publication segment_seconds=%.3f duration=%.3f state=%s",
                job.id,
                a.id,
                job.finding_id,
                job.revision,
                job.request_id,
                timings.get("segmentation", 0.0),
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

            try:
                self.repository.mutate(device, assessment_id, fail)
            except AppError as failure:
                if failure.code != "account_deleting":
                    raise
        finally:
            # Losing/deletion-racing uploads cannot leave assets behind. A process
            # crash is handled by recover(), using the pre-reserved asset reference.
            self.cleanup(device, assessment_id, job.id)

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

    async def _pipeline(self, device, a, job, deadline, stage, timings):
        # SAM always segments the initial photo the prompt was written for.
        photo = a.photo
        if job.photo_id != photo.id or job.image_digest != photo.sha256 or not photo.uploaded:
            raise ValueError("Source binding mismatch")
        try:
            data = await asyncio.to_thread(
                self.photos.get, device, a.id, photo, timeout=remaining(deadline)
            )
        except Exception:
            return "unavailable", "The original evidence photo is missing.", {}, None
        if hashlib.sha256(data).hexdigest() != photo.sha256:
            raise ValueError("Source digest mismatch")
        with Image.open(io.BytesIO(data)) as image:
            if image.getexif().get(274, 1) != 1:
                raise ValueError("Source orientation mismatch")
            size = image.size
        info = {"width": size[0], "height": size[1]}
        stage[0] = "segmentation"
        began = time.monotonic()
        candidates = await self.provider.segment(data, size, job.prompt, deadline)
        timings["segmentation"] = time.monotonic() - began
        remaining(deadline)
        if not candidates:
            return "unavailable", "No matching visible object was found.", info, None
        stage[0] = "validation"
        # Validate and rank even injected adapter output at the publication boundary.
        chosen = choose(candidates, size)
        info.update(region=chosen.region, confidence=chosen.confidence)
        return (
            "ready",
            None,
            info,
            await bounded_cpu(mask_overlay, chosen.mask, deadline=deadline),
        )

    def cleanup(self, device, assessment_id, annotation_id):
        try:
            a = self.repository.get(device, assessment_id)
        except AppError as exc:
            if exc.code != "account_deleting":
                raise
            a = None
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

    def pending(self):
        """Every active attempt, for recovery; each is claimed independently."""
        return [
            (a.owner_uid, a.id, j.id)
            for a in self.repository.annotation_pending()
            for j in a.annotations
            if j.state in ACTIVE
        ]

    def recover(self):
        """Serial recovery pass, used by tests; the local worker runs these concurrently."""
        self.reap_assets()
        for device, assessment_id, annotation_id in self.pending():
            # Lost attempts expire without ever repeating the provider call.
            self.work(device, assessment_id, annotation_id)

    def reap_assets(self):
        # Also covers a process dying after a deletion-racing upload when its
        # assessment document has already gone. Mask keys never overlap photos.
        for device, assessment_id, annotation_id in self.photos.annotation_assets():
            self.cleanup(device, assessment_id, annotation_id)
