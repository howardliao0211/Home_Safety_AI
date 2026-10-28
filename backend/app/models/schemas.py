from datetime import datetime, timezone
from typing import Annotated, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

Text = Annotated[str, Field(min_length=1, max_length=3000)]
Profile = Literal["Older adult", "Child", "Baby", "Pet"]
Severity = Literal["High", "Medium", "Low"]
FindingStatus = Literal["open", "resolved", "dismissed"]
OperationStatus = Literal["ready", "running", "failed", "complete"]
DISCLAIMER = (
    "AI-generated suggestions based on visible information only; "
    "not a professional home safety inspection."
)


def now() -> datetime:
    return datetime.now(timezone.utc)


def new_id() -> str:
    return str(uuid4())


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


# Shared output schemas make every property explicit; optional values use null.
class FollowUpSuggestion(StrictModel):
    kind: Literal["photo", "text"]
    question: Text


class FindingContent(StrictModel):
    title: Annotated[str, Field(min_length=1, max_length=160)]
    category: Annotated[str, Field(min_length=1, max_length=100)]
    severity: Severity
    evidence: Text
    recommendation: Text
    short_action: Annotated[str, Field(min_length=1, max_length=300)]
    uncertainty: Text


class ProposedFinding(FindingContent):
    follow_up: FollowUpSuggestion | None
    # Internal localisation metadata. Validated separately from safety content:
    # a missing or unusable value only makes this finding's highlight unavailable.
    segmentation_prompt: str | None

    @model_validator(mode="before")
    @classmethod
    def tolerate_segmentation_prompt(cls, data):
        if isinstance(data, dict):
            value = data.get("segmentation_prompt")
            data = {
                **data,
                "segmentation_prompt": value if value is None or isinstance(value, str) else "",
            }
        return data


class AssessmentResult(StrictModel):
    summary: Text
    findings: Annotated[list[ProposedFinding], Field(max_length=12)]


class RevisionResult(StrictModel):
    finding: FindingContent
    feedback: Text


class Photo(StrictModel):
    id: str = Field(default_factory=new_id)
    content_type: Literal["image/jpeg", "image/png", "image/webp"]
    sha256: str
    uploaded: bool = False


class Operation(StrictModel):
    status: OperationStatus = "ready"
    attempts: int = 0
    error: str | None = None
    request_id: str | None = None
    provider: str | None = None
    model: str | None = None


class Submission(Operation):
    id: str
    kind: Literal["follow-up", "review"]
    text: str = ""
    photo: Photo | None = None
    input_hash: str
    feedback: str | None = None
    created_at: datetime = Field(default_factory=now)


class FollowUp(FollowUpSuggestion):
    state: Literal["available", "skipped", "answered"] = "available"


AnnotationState = Literal["queued", "processing", "ready", "unavailable", "failed", "reported"]


class Region(StrictModel):
    x: float = Field(ge=0, le=1, allow_inf_nan=False)
    y: float = Field(ge=0, le=1, allow_inf_nan=False)
    width: float = Field(gt=0, le=1, allow_inf_nan=False)
    height: float = Field(gt=0, le=1, allow_inf_nan=False)


class Annotation(StrictModel):
    id: str = Field(default_factory=new_id)
    finding_id: str
    revision: str
    attempt: int
    state: AnnotationState = "queued"
    reason: str | None = None
    created_at: datetime = Field(default_factory=now)
    started_at: datetime | None = None
    finished_at: datetime | None = None
    photo_id: str | None = None
    photo_kind: Literal["original", "follow-up", "review"] | None = None
    image_digest: str | None = None
    width: int | None = None
    height: int | None = None
    orientation: Literal[1] = 1  # Uploads are EXIF-transposed before storage.
    target: str | None = None  # Legacy selection label.
    region: Region | None = None
    confidence: float | None = None
    review: Literal["approved", "rejected"] | None = None  # Legacy localisation review.
    feedback: Literal["wrong_object"] | None = None
    # Internal fields never cross the client API.
    lease_id: str | None = None
    expires_at: datetime | None = None
    mask: Photo | None = None
    prompt: str | None = None  # SAM concept from the initial assessment; absent on legacy records.
    request_id: str

    @model_validator(mode="after")
    def reject_late_publication(self):
        if (
            self.state == "ready"
            and self.finished_at
            and self.expires_at
            and self.finished_at > self.expires_at
        ):
            self.state = "failed"
            self.reason = "Highlight publication exceeded its deadline. Retry when ready."
        return self


class EvidenceSnapshot(StrictModel):
    revision: str
    content: FindingContent
    photo_ids: list[str]
    submission_ids: list[str]
    created_at: datetime = Field(default_factory=now)


class AnnotationRequest(StrictModel):
    revision: str = Field(min_length=1, max_length=100)
    retry: bool = False


class FeedbackRequest(StrictModel):
    kind: Literal["wrong_object"]


class Finding(FindingContent):
    id: str = Field(default_factory=new_id)
    status: FindingStatus = "open"
    note: str = ""
    follow_up: FollowUp | None = None
    submissions: list[Submission] = Field(default_factory=list)
    content_revision: str = "initial"
    evidence_history: list[EvidenceSnapshot] = Field(default_factory=list)


class Lease(StrictModel):
    id: str
    expires_at: datetime


class Assessment(Operation):
    id: str
    device_id: str
    created_at: datetime = Field(default_factory=now)
    updated_at: datetime = Field(default_factory=now)
    photo: Photo
    profiles: list[Profile]
    household_context: str = ""
    input_hash: str
    summary: str | None = None
    findings: list[Finding] = Field(default_factory=list)
    disclaimer: str = DISCLAIMER
    deleting: bool = False
    lease: Lease | None = None
    annotations: list[Annotation] = Field(default_factory=list)
    annotation_dispatch_pending: bool = False
    annotation_commits: dict[str, datetime] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_annotation_commits(self):
        for job in self.annotations:
            if job.id in self.annotation_commits:
                job.finished_at = self.annotation_commits[job.id]
                job.reject_late_publication()
        return self


class FindingPatch(StrictModel):
    status: FindingStatus
    note: str | None = Field(default=None, max_length=3000)
