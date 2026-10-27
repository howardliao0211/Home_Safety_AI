from datetime import datetime, timezone
from typing import Annotated, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

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


class Finding(FindingContent):
    id: str = Field(default_factory=new_id)
    status: FindingStatus = "open"
    note: str = ""
    follow_up: FollowUp | None = None
    submissions: list[Submission] = Field(default_factory=list)


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


class FindingPatch(StrictModel):
    status: FindingStatus
    note: str | None = Field(default=None, max_length=3000)
