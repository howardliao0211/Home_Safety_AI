import os
import time
from collections.abc import Callable
from typing import Protocol

from google.api_core.exceptions import FailedPrecondition, NotFound
from google.auth.credentials import AnonymousCredentials
from google.cloud import firestore

from app.config import Settings
from app.errors import AppError
from app.models.schemas import Assessment

Mutation = Callable[[Assessment | None], Assessment | None]


class AssessmentRepository(Protocol):
    def get(self, device_id: str, assessment_id: str) -> Assessment | None: ...
    def latest(self, device_id: str) -> Assessment | None: ...
    def mutate(
        self, device_id: str, assessment_id: str, change: Mutation, *, deadline: float | None = None
    ) -> Assessment | None:
        """Atomically read, apply a pure callback, and write/delete one assessment."""
        ...

    def annotation_pending(self) -> list[Assessment]: ...
    def close(self) -> None: ...


def check_size(assessment: Assessment):
    # Leave headroom below Firestore's 1 MiB document limit, including field overhead.
    if len(assessment.model_dump_json().encode()) > 750_000:
        raise AppError(409, "assessment_full", "This assessment has reached its storage limit.")


class FirestoreRepository:
    def __init__(self, settings: Settings):
        if settings.firestore_emulator_host:
            os.environ["FIRESTORE_EMULATOR_HOST"] = settings.firestore_emulator_host
        self.client = firestore.Client(
            project=settings.google_cloud_project,
            database=settings.firestore_database_id,
            credentials=AnonymousCredentials() if settings.firestore_emulator_host else None,
        )

    def collection(self, device_id: str):
        return self.client.collection("devices").document(device_id).collection("assessments")

    def get(self, device_id: str, assessment_id: str) -> Assessment | None:
        snapshot = self.collection(device_id).document(assessment_id).get(timeout=10)
        return Assessment.model_validate(snapshot.to_dict()) if snapshot.exists else None

    def latest(self, device_id: str) -> Assessment | None:
        # Deleted/in-progress deletions cannot hide the previous latest assessment.
        query = self.collection(device_id).order_by("created_at", direction="DESCENDING")
        for snapshot in query.stream(timeout=10):
            result = Assessment.model_validate(snapshot.to_dict())
            if not result.deleting:
                return result
        return None

    def mutate(
        self, device_id: str, assessment_id: str, change: Mutation, *, deadline: float | None = None
    ) -> Assessment | None:
        ref = self.collection(device_id).document(assessment_id)
        if deadline is not None:
            return self._bounded_mutate(ref, change, deadline)

        @firestore.transactional
        def run(transaction):
            snapshot = ref.get(transaction=transaction, timeout=10)
            previous = Assessment.model_validate(snapshot.to_dict()) if snapshot.exists else None
            updated = change(previous)
            if updated is None:
                transaction.delete(ref)
            else:
                check_size(updated)
                transaction.set(ref, updated.model_dump(mode="python"))
            return updated

        return run(self.client.transaction())

    def _bounded_mutate(self, ref, change, deadline):
        """Optimistic atomic claim/publication with an explicit end-to-end budget.

        The update-time precondition provides CAS atomicity. Unlike the high-level
        transaction wrapper, every read/write disables SDK retries and receives
        only the remaining budget. Conflicts re-read state, never repeat models.
        """

        def left():
            seconds = deadline - time.monotonic()
            if seconds <= 0:
                raise TimeoutError()
            return seconds

        while True:
            snapshot = ref.get(timeout=left(), retry=None)
            previous = Assessment.model_validate(snapshot.to_dict()) if snapshot.exists else None
            previous_states = {j.id: j.state for j in previous.annotations} if previous else {}
            updated = change(previous)
            if updated is None:
                return None  # Annotation work never creates or deletes assessments.
            check_size(updated)
            payload = updated.model_dump(mode="python")
            publishing = [
                j.id
                for j in updated.annotations
                if j.state == "ready" and previous_states.get(j.id) != "ready"
            ]
            for annotation_id in publishing:
                # Firestore transforms cannot occur inside arrays. A sibling map
                # supplies authoritative server commit times for deadline fencing.
                payload["annotation_commits"][annotation_id] = firestore.SERVER_TIMESTAMP
            try:
                result = ref.update(
                    payload,
                    option=self.client.write_option(last_update_time=snapshot.update_time),
                    timeout=left(),
                    retry=None,
                )
                for annotation_id in publishing:
                    updated.annotation_commits[annotation_id] = result.update_time
                return Assessment.model_validate(updated.model_dump())
            except FailedPrecondition:
                left()
            except NotFound:
                return change(None)

    def annotation_pending(self):
        # One-field collection-group index, provisioned in Terraform.
        query = self.client.collection_group("assessments").where(
            filter=firestore.FieldFilter("annotation_dispatch_pending", "==", True)
        )
        return [Assessment.model_validate(s.to_dict()) for s in query.stream(timeout=10)]

    def close(self):
        self.client.close()
