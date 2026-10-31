import json
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, Header, Query, Request, Response, UploadFile
from pydantic import TypeAdapter, ValidationError

from app.annotations.service import public_annotation
from app.assessments.chat import ChatService
from app.assessments.service import AssessmentService
from app.errors import AppError
from app.models.schemas import (
    AnnotationRequest,
    Assessment,
    ChatGeneration,
    ChatRequest,
    FeedbackRequest,
    FindingPatch,
    Profile,
)
from app.storage.photos import MAX_UPLOAD_BYTES, prepare_photo


def identity(request: Request, authorization: Annotated[str | None, Header()] = None):
    if not authorization or not authorization.startswith("Bearer "):
        raise AppError(401, "unauthorized", "Sign in to continue.")
    return request.app.state.identity.verify(authorization[7:])


def owner(request: Request, claims: Annotated[dict, Depends(identity)]) -> str:
    if claims.get("email_verified") is not True:
        raise AppError(403, "email_unverified", "Verify your email to continue.")
    if hasattr(request.app.state, "accounts"):
        request.app.state.accounts.accounts.require_active(claims["uid"])
    return claims["uid"]


router = APIRouter()


def service(request: Request) -> AssessmentService:
    return request.app.state.service


Service = Annotated[AssessmentService, Depends(service)]
Owner = Annotated[str, Depends(owner)]


def public(assessment: Assessment) -> dict:
    result = assessment.model_dump(
        mode="json",
        exclude={
            "lease",
            "input_hash",
            "owner_uid",
            "annotations",
            "annotation_dispatch_pending",
            "annotation_commits",
        },
    )
    for finding in result["findings"]:
        finding.pop("chat", None)
        finding.pop("chat_blocked", None)
        jobs = [j for j in assessment.annotations if j.finding_id == finding["id"]]
        finding["annotations"] = [public_annotation(j) for j in jobs]
        finding["annotation"] = next(
            (
                public_annotation(j)
                for j in reversed(jobs)
                if j.revision == finding["content_revision"]
            ),
            None,
        )
        for submission in finding["submissions"]:
            submission.pop("input_hash")
    return result


def read_photo(photo: UploadFile):
    try:
        return prepare_photo(photo.file.read(MAX_UPLOAD_BYTES + 1))
    finally:
        photo.file.close()


@router.get("/health")
def health():
    # Liveness only; startup constructs the configured provider and storage clients.
    return {"status": "ok"}


@router.post("/v1/assessments", status_code=201)
def create_assessment(
    svc: Service,
    device: Owner,
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
def latest_assessment(svc: Service, device: Owner):
    return public(svc.latest(device))


@router.get("/v1/assessments")
def assessment_history(
    svc: Service,
    device: Owner,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    cursor: Annotated[str | None, Query(min_length=1, max_length=2048)] = None,
):
    return svc.history(device, limit, cursor)


@router.get("/v1/assessments/{assessment_id}")
def get_assessment(assessment_id: UUID, svc: Service, device: Owner):
    return public(svc.get(device, str(assessment_id)))


@router.post("/v1/assessments/{assessment_id}/analyze")
def analyze(assessment_id: UUID, svc: Service, device: Owner, request: Request):
    return public(svc.analyze(device, str(assessment_id), request.state.request_id))


@router.patch("/v1/assessments/{assessment_id}/findings/{finding_id}")
def patch_finding(
    assessment_id: UUID, finding_id: UUID, patch: FindingPatch, svc: Service, device: Owner
):
    return public(svc.patch_finding(device, str(assessment_id), str(finding_id), patch))


@router.post("/v1/assessments/{assessment_id}/findings/{finding_id}/skip-follow-up")
def skip_follow_up(assessment_id: UUID, finding_id: UUID, svc: Service, device: Owner):
    return public(svc.skip_follow_up(device, str(assessment_id), str(finding_id)))


@router.post("/v1/assessments/{assessment_id}/findings/{finding_id}/submissions", status_code=201)
def add_submission(
    assessment_id: UUID,
    finding_id: UUID,
    svc: Service,
    device: Owner,
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
    device: Owner,
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
def get_photo(assessment_id: UUID, photo_id: UUID, svc: Service, device: Owner):
    metadata, data = svc.get_photo(device, str(assessment_id), str(photo_id))
    return Response(
        data,
        media_type=metadata.content_type,
        headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
    )


@router.delete("/v1/assessments/{assessment_id}", status_code=204)
def delete_assessment(assessment_id: UUID, svc: Service, device: Owner):
    svc.delete(device, str(assessment_id))
    return Response(status_code=204)


ANNOTATIONS = "/v1/assessments/{assessment_id}/findings/{finding_id}/annotations"


@router.post(ANNOTATIONS)
def request_annotation(
    assessment_id: UUID,
    finding_id: UUID,
    body: AnnotationRequest,
    request: Request,
    response: Response,
    device: Owner,
):
    result = request.app.state.annotations.request(
        device, str(assessment_id), str(finding_id), body, request.state.request_id
    )
    response.status_code = 202 if result["state"] in {"queued", "processing"} else 200
    return result


@router.get(ANNOTATIONS + "/{annotation_id}")
def get_annotation(
    assessment_id: UUID, finding_id: UUID, annotation_id: UUID, request: Request, device: Owner
):
    return public_annotation(
        request.app.state.annotations.get(
            device, str(assessment_id), str(finding_id), str(annotation_id)
        )
    )


@router.get(ANNOTATIONS + "/{annotation_id}/mask")
def get_mask(
    assessment_id: UUID, finding_id: UUID, annotation_id: UUID, request: Request, device: Owner
):
    data = request.app.state.annotations.mask(
        device, str(assessment_id), str(finding_id), str(annotation_id)
    )
    return Response(
        data,
        media_type="image/png",
        headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
    )


@router.post(ANNOTATIONS + "/{annotation_id}/feedback")
def report_annotation(
    assessment_id: UUID,
    finding_id: UUID,
    annotation_id: UUID,
    body: FeedbackRequest,
    request: Request,
    device: Owner,
):
    return request.app.state.annotations.feedback(
        device, str(assessment_id), str(finding_id), str(annotation_id)
    )


@router.post("/v1/account/deletion", status_code=202)
def delete_account(request: Request, claims: Annotated[dict, Depends(identity)]):
    return request.app.state.accounts.begin(claims)


@router.post("/v1/account/deletion/status")
def deletion_status(request: Request, x_deletion_receipt: Annotated[str, Header(max_length=200)]):
    # Receipt is carried in a header, never in access-logged URLs.
    return request.app.state.accounts.accounts.status(x_deletion_receipt)


CHAT = "/v1/assessments/{assessment_id}/findings/{finding_id}/chat"


@router.get(CHAT)
def get_chat(assessment_id: UUID, finding_id: UUID, svc: Service, device: Owner):
    return ChatService(svc).get(device, str(assessment_id), str(finding_id))


@router.post(CHAT + "/turns", status_code=201)
def accept_chat(
    assessment_id: UUID, finding_id: UUID, body: ChatRequest, svc: Service, device: Owner
):
    return ChatService(svc).accept(device, str(assessment_id), str(finding_id), body)


@router.post(CHAT + "/turns/{turn_id}/generate")
def generate_chat(
    assessment_id: UUID,
    finding_id: UUID,
    turn_id: UUID,
    body: ChatGeneration,
    request: Request,
    svc: Service,
    device: Owner,
):
    return ChatService(svc).generate(
        device,
        str(assessment_id),
        str(finding_id),
        str(turn_id),
        body.attempt_id,
        request.state.request_id,
    )
