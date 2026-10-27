import hmac
import json
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, Header, Request, Response, UploadFile
from pydantic import TypeAdapter, ValidationError

from app.assessments.service import AssessmentService
from app.errors import AppError
from app.models.schemas import Assessment, FindingPatch, Profile
from app.storage.photos import MAX_UPLOAD_BYTES, prepare_photo


def authorize(request: Request, authorization: Annotated[str | None, Header()] = None):
    token = request.app.state.settings.demo_bearer_token
    if token and not hmac.compare_digest(
        (authorization or "").encode(), f"Bearer {token.get_secret_value()}".encode()
    ):
        raise AppError(401, "unauthorized", "A valid demo bearer token is required.")


router = APIRouter(dependencies=[Depends(authorize)])


def device_id(x_device_id: Annotated[UUID, Header()]) -> str:
    return str(x_device_id)


def service(request: Request) -> AssessmentService:
    return request.app.state.service


Service = Annotated[AssessmentService, Depends(service)]
Device = Annotated[str, Depends(device_id)]


def public(assessment: Assessment) -> dict:
    result = assessment.model_dump(mode="json", exclude={"lease", "input_hash", "device_id"})
    for finding in result["findings"]:
        for submission in finding["submissions"]:
            submission.pop("input_hash")
    return result


def read_photo(photo: UploadFile):
    try:
        return prepare_photo(photo.file.read(MAX_UPLOAD_BYTES + 1))
    finally:
        photo.file.close()


@router.get("/healthz")
def health():
    # Liveness only; startup constructs the configured provider and storage clients.
    return {"status": "ok"}


@router.post("/v1/assessments", status_code=201)
def create_assessment(
    svc: Service,
    device: Device,
    assessment_id: Annotated[UUID, Form()],
    photo: Annotated[UploadFile, File()],
    profiles: Annotated[str, Form(max_length=200)] = "[]",
    household_context: Annotated[str, Form(max_length=3000)] = "",
):
    try:
        selected = TypeAdapter(list[Profile]).validate_python(json.loads(profiles))
    except (ValidationError, ValueError):
        raise AppError(
            422,
            "invalid_profiles",
            "profiles must be a JSON array of Older adult, Child, Baby, Pet.",
        ) from None
    selected = list(dict.fromkeys(selected))
    metadata, data = read_photo(photo)
    return public(
        svc.create(device, str(assessment_id), metadata, data, selected, household_context)
    )


@router.get("/v1/assessments/latest")
def latest_assessment(svc: Service, device: Device):
    return public(svc.latest(device))


@router.get("/v1/assessments/{assessment_id}")
def get_assessment(assessment_id: UUID, svc: Service, device: Device):
    return public(svc.get(device, str(assessment_id)))


@router.post("/v1/assessments/{assessment_id}/analyze")
def analyze(assessment_id: UUID, svc: Service, device: Device, request: Request):
    return public(svc.analyze(device, str(assessment_id), request.state.request_id))


@router.patch("/v1/assessments/{assessment_id}/findings/{finding_id}")
def patch_finding(
    assessment_id: UUID, finding_id: UUID, patch: FindingPatch, svc: Service, device: Device
):
    return public(svc.patch_finding(device, str(assessment_id), str(finding_id), patch))


@router.post("/v1/assessments/{assessment_id}/findings/{finding_id}/skip-follow-up")
def skip_follow_up(assessment_id: UUID, finding_id: UUID, svc: Service, device: Device):
    return public(svc.skip_follow_up(device, str(assessment_id), str(finding_id)))


@router.post("/v1/assessments/{assessment_id}/findings/{finding_id}/submissions", status_code=201)
def add_submission(
    assessment_id: UUID,
    finding_id: UUID,
    svc: Service,
    device: Device,
    submission_id: Annotated[UUID, Form()],
    kind: Annotated[Literal["follow-up", "review"], Form()],
    text: Annotated[str, Form(max_length=3000)] = "",
    photo: Annotated[UploadFile | None, File()] = None,
):
    metadata, data = read_photo(photo) if photo else (None, None)
    return public(
        svc.add_submission(
            device,
            str(assessment_id),
            str(finding_id),
            str(submission_id),
            kind,
            text,
            metadata,
            data,
        )
    )


@router.post(
    "/v1/assessments/{assessment_id}/findings/{finding_id}/submissions/{submission_id}/analyze"
)
def analyze_submission(
    assessment_id: UUID,
    finding_id: UUID,
    submission_id: UUID,
    svc: Service,
    device: Device,
    request: Request,
):
    return public(
        svc.analyze(
            device,
            str(assessment_id),
            request.state.request_id,
            str(finding_id),
            str(submission_id),
        )
    )


@router.get("/v1/assessments/{assessment_id}/photos/{photo_id}")
def get_photo(assessment_id: UUID, photo_id: UUID, svc: Service, device: Device):
    metadata, data = svc.get_photo(device, str(assessment_id), str(photo_id))
    return Response(
        data,
        media_type=metadata.content_type,
        headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
    )


@router.delete("/v1/assessments/{assessment_id}", status_code=204)
def delete_assessment(assessment_id: UUID, svc: Service, device: Device):
    svc.delete(device, str(assessment_id))
    return Response(status_code=204)
