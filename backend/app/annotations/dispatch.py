"""Cloud Tasks deliveries and Scheduler recovery use verified service OIDC.

Local development calls AnnotationService.work/recover directly, never a public
unauthenticated worker route. Queue recovery does not depend on mobile polling.
"""

import json
from typing import Literal

from fastapi import APIRouter, Depends, Request
from google.auth.transport.requests import Request as GoogleRequest
from google.cloud import tasks_v2
from google.oauth2 import id_token
from pydantic import BaseModel

from app.errors import AppError


class CloudTasksDispatcher:
    def __init__(self, settings):
        self.settings = settings

    def enqueue(self, device, assessment_id, annotation_id):
        config = self.settings
        with tasks_v2.CloudTasksClient() as client:
            client.create_task(
                parent=config.annotation_tasks_queue,
                task={
                    "http_request": {
                        "http_method": tasks_v2.HttpMethod.POST,
                        "url": config.annotation_worker_url + "/internal/annotations/work",
                        "headers": {"Content-Type": "application/json"},
                        "body": json.dumps(
                            {
                                "version": 2,
                                "owner_uid": device,
                                "assessment_id": assessment_id,
                                "annotation_id": annotation_id,
                            }
                        ).encode(),
                        "oidc_token": {
                            "service_account_email": config.annotation_worker_service_account,
                            "audience": config.annotation_worker_url,
                        },
                    },
                    "dispatch_deadline": {"seconds": 60},
                },
                timeout=5,
                retry=None,
            )

    def enqueue_chat(self, device, assessment_id, finding_id, turn_id, attempt_id):
        from app.assessments.chat import TASK_DEADLINE_SECONDS

        config = self.settings
        with tasks_v2.CloudTasksClient() as client:
            client.create_task(
                parent=config.annotation_tasks_queue,
                task={
                    "http_request": {
                        "http_method": tasks_v2.HttpMethod.POST,
                        "url": config.annotation_worker_url + "/internal/chat/work",
                        "headers": {"Content-Type": "application/json"},
                        "body": json.dumps(
                            {
                                "version": 1,
                                "owner_uid": device,
                                "assessment_id": assessment_id,
                                "finding_id": finding_id,
                                "turn_id": turn_id,
                                "attempt_id": attempt_id,
                            }
                        ).encode(),
                        "oidc_token": {
                            "service_account_email": config.annotation_worker_service_account,
                            "audience": config.annotation_worker_url,
                        },
                    },
                    "dispatch_deadline": {"seconds": TASK_DEADLINE_SECONDS},
                },
                timeout=5,
                retry=None,
            )


def worker_auth(request: Request):
    settings = request.app.state.settings
    authorization = request.headers.get("Authorization", "")
    if not settings.annotation_worker_url or not authorization.startswith("Bearer "):
        raise AppError(401, "unauthorized", "Service authentication required.")
    try:
        claims = id_token.verify_oauth2_token(
            authorization[7:], GoogleRequest(), audience=settings.annotation_worker_url
        )
        if (
            claims.get("email") != settings.annotation_worker_service_account
            or claims.get("email_verified") is not True
        ):
            raise ValueError("Wrong service identity")
    except Exception:
        raise AppError(401, "unauthorized", "Service authentication required.") from None


worker_router = APIRouter(dependencies=[Depends(worker_auth)])


class Delivery(BaseModel):
    version: Literal[2]
    owner_uid: str
    assessment_id: str
    annotation_id: str


@worker_router.post("/internal/annotations/work")
def work(body: Delivery, request: Request):
    request.app.state.annotations.work(body.owner_uid, body.assessment_id, body.annotation_id)
    return {"accepted": True}


class ChatDelivery(BaseModel):
    version: Literal[1]
    owner_uid: str
    assessment_id: str
    finding_id: str
    turn_id: str
    attempt_id: str


@worker_router.post("/internal/chat/work")
def chat_work(body: ChatDelivery, request: Request):
    # Always acknowledge: outcomes are persisted, and redelivery never re-runs a claim.
    request.app.state.chat.work(
        body.owner_uid,
        body.assessment_id,
        body.finding_id,
        body.turn_id,
        body.attempt_id,
        request.state.request_id,
    )
    return {"accepted": True}


@worker_router.post("/internal/annotations/recover")
def recover(request: Request):
    if hasattr(request.app.state, "accounts"):
        request.app.state.accounts.recover()
    service = request.app.state.annotations
    service.reap_assets()
    for a in service.repository.annotation_pending():
        # Re-delivery is safe: expired claims become failed, never re-run.
        service.dispatch(a.owner_uid, a.id)
    request.app.state.chat.recover()
    return {"accepted": True}
