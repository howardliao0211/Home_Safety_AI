from datetime import datetime, timezone
from typing import Annotated, Literal
from uuid import UUID, uuid4

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


Suggestion = Annotated[str, Field(min_length=1, max_length=500)]
SUGGESTION_COUNT = 3


class AssessmentResult(StrictModel):
    title: Annotated[str | None, Field(max_length=3000)]
    # Structured plain-text items: exactly three with findings, none without.
    suggestions: Annotated[list[Suggestion], Field(max_length=SUGGESTION_COUNT)]
    findings: Annotated[list[ProposedFinding], Field(max_length=12)]

    @model_validator(mode="after")
    def validate_suggestions(self):
        expected = SUGGESTION_COUNT if self.findings else 0
        if len(self.suggestions) != expected:
            raise ValueError(f"Expected {expected} suggestions.")
        keys = {item.strip().casefold() for item in self.suggestions}
        if "" in keys or len(keys) != len(self.suggestions):
            raise ValueError("Suggestions must be distinct and nonblank.")
        return self

    @model_validator(mode="before")
    @classmethod
    def tolerate_missing_title(cls, data):
        if isinstance(data, dict) and "title" not in data:
            return {**data, "title": None}
        return data


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


# "ready" is a legacy accepted-but-unstarted turn; new turns start "queued".
ChatStatus = Literal["ready", "queued", "running", "failed", "complete"]


class ChatTurn(StrictModel):
    id: str
    question: str = Field(min_length=1, max_length=2000)
    answer: str | None = None
    status: ChatStatus = "ready"
    error: str | None = None
    # Safe failure category, e.g. interrupted, provider_failed, truncated, context_limit.
    error_code: str | None = None
    created_at: datetime = Field(default_factory=now)
    finished_at: datetime | None = None
    attempt_ids: list[str] = Field(default_factory=list)
    # Bounded text published so far by the current attempt; kept (as an incomplete
    # response) when it fails, cleared by an explicit retry, never sent to the model.
    partial: str = ""
    # Monotonic progress version: clients ignore snapshots older than one they hold.
    version: int = 0
    queued_until: datetime | None = None
    started_at: datetime | None = None
    expires_at: datetime | None = None
    execution: str | None = None


class ChatRequest(StrictModel):
    id: UUID
    question: str = Field(min_length=1, max_length=2000)


class ChatGeneration(StrictModel):
    attempt_id: UUID


class Finding(FindingContent):
    chat: list[ChatTurn] = Field(default_factory=list)
    chat_blocked: str | None = None
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


class RoomConcept(StrictModel):
    state: Literal["not_applicable", "unavailable", "queued", "running", "ready", "failed"]
    attempt_id: str = Field(default_factory=new_id)
    attempts: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=now)
    queued_until: datetime | None = None
    started_at: datetime | None = None
    expires_at: datetime | None = None
    finished_at: datetime | None = None
    execution: str | None = None
    error_code: str | None = None
    model: str | None = None
    prompt_version: str = "room-concept-v1"
    request_id: str = Field(default_factory=new_id)
    prompt: str = ""
    source_photo: Photo | None = None
    asset: Photo | None = None
    width: int | None = None
    height: int | None = None


class Assessment(Operation):
    id: str
    owner_uid: str
    created_at: datetime = Field(default_factory=now)
    updated_at: datetime = Field(default_factory=now)
    photo: Photo
    profiles: list[Profile]
    household_context: str = ""
    input_hash: str
    summary: str | None = None  # Legacy prose; new results use suggestions.
    # None: legacy/not yet analysed. []: new result with no findings.
    suggestions: list[str] | None = None
    title: Annotated[str | None, Field(max_length=3000)] = None
    findings: list[Finding] = Field(default_factory=list)
    disclaimer: str = DISCLAIMER
    deleting: bool = False
    lease: Lease | None = None
    annotations: list[Annotation] = Field(default_factory=list)
    annotation_dispatch_pending: bool = False
    # Recovery index: some chat turn is queued or running.
    chat_dispatch_pending: bool = False
    annotation_commits: dict[str, datetime] = Field(default_factory=dict)
    room_concept: RoomConcept | None = None
    room_concept_dispatch_pending: bool = False
    room_concept_commit: datetime | None = None

    @model_validator(mode="after")
    def validate_annotation_commits(self):
        if self.room_concept and self.room_concept_commit and self.room_concept.state == "ready":
            job = self.room_concept
            job.finished_at = self.room_concept_commit
            if job.expires_at and job.finished_at > job.expires_at:
                job.state, job.error_code = "failed", "publication_timeout"
        for job in self.annotations:
            if job.id in self.annotation_commits:
                job.finished_at = self.annotation_commits[job.id]
                job.reject_late_publication()
        return self


class FindingPatch(StrictModel):
    status: FindingStatus
    note: str | None = Field(default=None, max_length=3000)
