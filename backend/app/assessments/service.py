import hashlib
import json
import logging
from datetime import timedelta

from pydantic import ValidationError

from app.assessments.prompts import ASSESS, REVISE
from app.errors import AppError, ModelError
from app.models.providers.base import ImageInput, ModelProvider
from app.models.schemas import (
    Assessment,
    AssessmentResult,
    Finding,
    FindingPatch,
    FollowUp,
    Lease,
    RevisionResult,
    Submission,
    new_id,
    now,
)
from app.storage.photos import PhotoStore
from app.storage.repository import AssessmentRepository

logger = logging.getLogger(__name__)
# Bounds cloud I/O and model calls; a crashed worker becomes manually retryable after expiry.
LEASE_SECONDS = 300


def fingerprint(value: dict) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def require(assessment: Assessment | None, *, allow_deleting=False) -> Assessment:
    if assessment is None:
        raise AppError(404, "not_found", "Assessment not found.")
    if assessment.deleting and not allow_deleting:
        raise AppError(409, "deleting", "Deletion is in progress. Retry deleting this assessment.")
    return assessment


def idle(assessment: Assessment):
    if assessment.lease and assessment.lease.expires_at > now():
        raise AppError(409, "busy", "An operation is in progress. Try again after it finishes.")


def finding_in(assessment: Assessment, finding_id: str) -> Finding:
    for finding in assessment.findings:
        if finding.id == finding_id:
            return finding
    raise AppError(404, "not_found", "Finding not found.")


def submission_in(finding: Finding, submission_id: str) -> Submission:
    for submission in finding.submissions:
        if submission.id == submission_id:
            return submission
    raise AppError(404, "not_found", "Submission not found.")


class AssessmentService:
    def __init__(
        self,
        repository: AssessmentRepository,
        photos: PhotoStore,
        provider: ModelProvider,
        annotations=None,
    ):
        self.repository, self.photos, self.provider = repository, photos, provider
        self.annotations = annotations

    def get(self, owner_uid: str, assessment_id: str) -> Assessment:
        return require(self.repository.get(owner_uid, assessment_id))

    def latest(self, owner_uid: str) -> Assessment:
        return require(self.repository.latest(owner_uid))

    def history(self, owner_uid: str, limit: int, cursor: str | None):
        from app.assessments.history import decode_cursor, encode_cursor, history_item

        after = decode_cursor(cursor, owner_uid) if cursor else None
        records = self.repository.history(owner_uid, limit + 1, after)
        page = records[:limit]
        return {
            "items": [history_item(a) for a in page],
            "next_cursor": encode_cursor(owner_uid, page[-1]) if len(records) > limit else None,
        }

    def _mutate(self, owner_uid, assessment_id, change, *, lease_id=None):
        def apply(previous):
            assessment = require(previous)
            if lease_id:
                if not assessment.lease or assessment.lease.id != lease_id:
                    raise AppError(
                        409, "superseded", "This operation was superseded. Reload the assessment."
                    )
            else:
                idle(assessment)
            before = assessment.model_dump()
            change(assessment)
            if assessment.model_dump() != before:
                assessment.updated_at = now()
            return assessment

        return self.repository.mutate(owner_uid, assessment_id, apply)

    def _upload(
        self,
        owner_uid,
        assessment_id,
        photo,
        data,
        lease_id,
        *,
        finding_id=None,
        submission_id=None,
    ):
        try:
            if photo and not photo.uploaded:
                self.photos.put(owner_uid, assessment_id, photo, data)

            def finish(assessment):
                target_photo = (
                    assessment.photo
                    if not submission_id
                    else submission_in(finding_in(assessment, finding_id), submission_id).photo
                )
                if target_photo:
                    target_photo.uploaded = True
                assessment.lease = None

            return self._mutate(owner_uid, assessment_id, finish, lease_id=lease_id)
        except Exception as exc:
            if isinstance(exc, AppError) and exc.code in {"superseded", "not_found", "deleting"}:
                raise
            self._release(owner_uid, assessment_id, lease_id)
            logger.error(
                "photo_upload_failed assessment_id=%s finding_id=%s exception_type=%s",
                assessment_id,
                finding_id,
                type(exc).__name__,
            )
            raise AppError(
                503, "upload_failed", "Photo upload failed. Resend the same input with the same ID."
            ) from None

    def _release(self, owner_uid, assessment_id, lease_id):
        self._mutate(
            owner_uid, assessment_id, lambda a: setattr(a, "lease", None), lease_id=lease_id
        )

    def create(self, owner_uid, assessment_id, photo, data, profiles, household_context):
        digest = fingerprint(
            {"photo": photo.sha256, "profiles": profiles, "context": household_context}
        )
        lease = Lease(id=new_id(), expires_at=now() + timedelta(seconds=LEASE_SECONDS))

        def reserve(previous):
            if previous:
                assessment = require(previous)
                if assessment.input_hash != digest:
                    raise AppError(
                        409, "id_conflict", "This assessment ID belongs to different input."
                    )
                if assessment.photo.uploaded:
                    return assessment
                idle(assessment)
            else:
                assessment = Assessment(
                    id=assessment_id,
                    owner_uid=owner_uid,
                    photo=photo,
                    profiles=profiles,
                    household_context=household_context,
                    input_hash=digest,
                )
            assessment.lease = lease
            return assessment

        assessment = self.repository.mutate(owner_uid, assessment_id, reserve)
        if assessment.photo.uploaded:
            return assessment
        return self._upload(owner_uid, assessment_id, assessment.photo, data, lease.id)

    def add_submission(
        self, owner_uid, assessment_id, finding_id, submission_id, kind, text, photo, data
    ):
        digest = fingerprint({"kind": kind, "text": text, "photo": photo.sha256 if photo else None})
        lease = Lease(id=new_id(), expires_at=now() + timedelta(seconds=LEASE_SECONDS))

        def reserve(assessment):
            if assessment.status != "complete":
                raise AppError(409, "not_assessed", "Finish the initial assessment first.")
            finding = finding_in(assessment, finding_id)
            existing = next((s for s in finding.submissions if s.id == submission_id), None)
            if existing:
                if existing.input_hash != digest:
                    raise AppError(
                        409, "id_conflict", "This submission ID belongs to different input."
                    )
            else:
                if kind == "review" and not photo:
                    raise AppError(
                        422, "photo_required", "A user-requested review requires a new photo."
                    )
                if kind == "follow-up":
                    follow_up = finding.follow_up
                    if (
                        not follow_up
                        or follow_up.state != "available"
                        or any(s.kind == "follow-up" for s in finding.submissions)
                    ):
                        raise AppError(
                            409,
                            "follow_up_unavailable",
                            "This follow-up was skipped or already submitted.",
                        )
                    if follow_up.kind == "photo" and not photo:
                        raise AppError(422, "photo_required", "This follow-up requires a photo.")
                    if follow_up.kind == "text" and not text.strip():
                        raise AppError(
                            422, "text_required", "Answer the clarification question with text."
                        )
                if len(finding.submissions) >= 20:
                    raise AppError(
                        409, "submission_limit", "This finding has reached its submission limit."
                    )
                finding.submissions.append(
                    Submission(
                        id=submission_id, kind=kind, text=text, photo=photo, input_hash=digest
                    )
                )
            assessment.lease = lease

        assessment = self._mutate(owner_uid, assessment_id, reserve)
        stored = submission_in(finding_in(assessment, finding_id), submission_id)
        return self._upload(
            owner_uid,
            assessment_id,
            stored.photo,
            data,
            lease.id,
            finding_id=finding_id,
            submission_id=submission_id,
        )

    def patch_finding(self, owner_uid, assessment_id, finding_id, patch: FindingPatch):
        def change(assessment):
            finding = finding_in(assessment, finding_id)
            finding.status = patch.status
            if patch.note is not None:
                finding.note = patch.note

        return self._mutate(owner_uid, assessment_id, change)

    def skip_follow_up(self, owner_uid, assessment_id, finding_id):
        def change(assessment):
            finding = finding_in(assessment, finding_id)
            if not finding.follow_up or any(s.kind == "follow-up" for s in finding.submissions):
                raise AppError(409, "follow_up_unavailable", "This follow-up cannot be skipped.")
            if finding.follow_up.state == "answered":
                raise AppError(409, "follow_up_unavailable", "This follow-up was already answered.")
            finding.follow_up.state = "skipped"

        return self._mutate(owner_uid, assessment_id, change)

    def analyze(self, owner_uid, assessment_id, request_id, finding_id=None, submission_id=None):
        lease = Lease(id=new_id(), expires_at=now() + timedelta(seconds=LEASE_SECONDS))

        def target(assessment):
            return (
                submission_in(finding_in(assessment, finding_id), submission_id)
                if submission_id
                else assessment
            )

        def claim(assessment):
            operation = target(assessment)
            if operation.status == "complete":
                return
            if not assessment.photo.uploaded or (
                submission_id and operation.photo and not operation.photo.uploaded
            ):
                raise AppError(
                    409,
                    "upload_incomplete",
                    "Resend the photo with its original ID before analysis.",
                )
            assessment.lease = lease
            operation.status = "running"
            operation.attempts += 1
            operation.error = None
            operation.request_id = request_id
            operation.provider, operation.model = self.provider.name, self.provider.model

        assessment = self._mutate(owner_uid, assessment_id, claim)
        if target(assessment).status == "complete":
            return assessment
        operation_name = "assess" if not submission_id else target(assessment).kind
        try:
            context = {
                "profiles": assessment.profiles,
                "household_context": assessment.household_context,
            }
            images = [self._image(owner_uid, assessment, assessment.photo, "Initial room photo")]
            schema = AssessmentResult
            if submission_id:
                finding = finding_in(assessment, finding_id)
                submission = submission_in(finding, submission_id)
                context.update(
                    {
                        "finding": finding.model_dump(
                            mode="json", exclude={"submissions", "evidence_history"}
                        ),
                        "earlier_completed_submissions": [
                            {"text": s.text, "feedback": s.feedback, "kind": s.kind}
                            for s in finding.submissions
                            if s.status == "complete"
                        ],
                        "submission_kind": submission.kind,
                        "submitted_text": submission.text,
                    }
                )
                if submission.photo:
                    images.append(
                        self._image(owner_uid, assessment, submission.photo, "New linked photo")
                    )
                schema = RevisionResult
            raw = self.provider.generate(
                system=REVISE if submission_id else ASSESS,
                context=context,
                images=images,
                schema=schema,
            )
            result = schema.model_validate(raw)

            def complete(current):
                current_operation = target(current)
                if submission_id:
                    from app.annotations.service import snapshot

                    snapshot(current, finding_in(current, finding_id))
                current_operation.status = "complete"
                current_operation.error = None
                if submission_id:
                    current_finding = finding_in(current, finding_id)
                    current_finding.content_revision = new_id()
                    for key, value in result.finding.model_dump().items():
                        setattr(current_finding, key, value)
                    current_operation.feedback = result.feedback
                    if current_operation.kind == "follow-up":
                        current_finding.follow_up.state = "answered"
                else:
                    proposed = sorted(
                        result.findings,
                        key=lambda item: {"High": 0, "Medium": 1, "Low": 2}[item.severity],
                    )
                    current.summary = result.summary
                    current.title = result.title
                    current.findings = [
                        Finding(
                            **item.model_dump(exclude={"follow_up", "segmentation_prompt"}),
                            follow_up=FollowUp(**item.follow_up.model_dump())
                            if item.follow_up
                            else None,
                        )
                        for item in proposed
                    ]
                    if self.annotations:
                        # Same commit as the findings, so a crash cannot lose highlight work.
                        self.annotations.seed(current, proposed, request_id)
                current.lease = None

            completed = self._mutate(owner_uid, assessment_id, complete, lease_id=lease.id)
            if self.annotations and not submission_id:
                # Enqueue failure leaves durable intent for the recovery sweep.
                self.annotations.dispatch(owner_uid, assessment_id)
            return completed
        except Exception as exc:
            if isinstance(exc, AppError) and exc.code in {"superseded", "not_found", "deleting"}:
                raise
            if isinstance(exc, ModelError):
                category, upstream_status = exc.category, exc.upstream_status
            else:
                category = (
                    "schema_validation"
                    if isinstance(exc, ValidationError)
                    else "internal_or_storage"
                )
                upstream_status = None
            # Exception bodies can contain API keys, inline images, or private model input.
            # Log safe diagnostics and code locations rather than exception text/locals.
            frames = []
            trace = exc.__traceback__
            while trace:
                frames.append(f"{trace.tb_frame.f_code.co_name}:{trace.tb_lineno}")
                trace = trace.tb_next
            logger.error(
                "analysis_failed operation=%s assessment_id=%s finding_id=%s submission_id=%s "
                "request_id=%s category=%s upstream_status=%s exception_type=%s frames=%s",
                operation_name,
                assessment_id,
                finding_id,
                submission_id,
                request_id,
                category,
                upstream_status,
                type(exc).__name__,
                ",".join(frames),
            )
            message = "Analysis failed. Your input is saved. Retry this operation when ready."
            code = "analysis_failed"
            if upstream_status in {401, 403} or category == "credentials_rejected":
                code = "model_credentials_rejected"
                message = "The model provider rejected the backend credentials. Correct the API key, restart the backend, then retry. Your input is saved."
            elif upstream_status == 429:
                code = "model_rate_limited"
                message = "The model provider rate limit or quota was reached. Check your quota, then retry later. Your input is saved."

            def fail(current):
                operation = target(current)
                operation.status = "failed"
                operation.error = message
                current.lease = None

            self._mutate(owner_uid, assessment_id, fail, lease_id=lease.id)
            raise AppError(502, code, message) from None

    def _image(self, owner_uid, assessment, photo, label):
        return ImageInput(
            label, photo.content_type, self.photos.get(owner_uid, assessment.id, photo)
        )

    def get_photo(self, owner_uid, assessment_id, photo_id):
        assessment = self.get(owner_uid, assessment_id)
        candidates = [assessment.photo] + [
            s.photo for f in assessment.findings for s in f.submissions if s.photo
        ]
        photo = next((p for p in candidates if p.id == photo_id and p.uploaded), None)
        if not photo:
            raise AppError(404, "not_found", "Photo not found.")
        return photo, self.photos.get(owner_uid, assessment_id, photo)

    def delete(self, owner_uid, assessment_id):
        lease = Lease(id=new_id(), expires_at=now() + timedelta(seconds=LEASE_SECONDS))

        def tombstone(previous):
            if previous is None:
                return None
            idle(previous)
            previous.deleting = True
            previous.annotation_dispatch_pending = False
            for annotation in previous.annotations:
                if annotation.state in {"queued", "processing"}:
                    annotation.state = "failed"
                    annotation.reason = "Assessment deletion cancelled this highlight."
                    annotation.finished_at = now()
            previous.lease = lease
            return previous

        assessment = self.repository.mutate(owner_uid, assessment_id, tombstone)
        if assessment is None:
            raise AppError(404, "not_found", "Assessment not found.")
        try:
            self.photos.delete_assessment(owner_uid, assessment_id)
        except Exception as exc:

            def unlock(previous):
                current = require(previous, allow_deleting=True)
                if current.lease and current.lease.id == lease.id:
                    current.lease = None
                return current

            self.repository.mutate(owner_uid, assessment_id, unlock)
            logger.error(
                "delete_failed assessment_id=%s exception_type=%s",
                assessment_id,
                type(exc).__name__,
            )
            raise AppError(
                503,
                "delete_failed",
                "Deletion is incomplete. Retry DELETE to finish removing photos and data.",
            ) from None

        def finish(previous):
            current = require(previous, allow_deleting=True)
            if not current.lease or current.lease.id != lease.id:
                raise AppError(409, "superseded", "Deletion was superseded. Retry DELETE.")
            return None

        self.repository.mutate(owner_uid, assessment_id, finish)
