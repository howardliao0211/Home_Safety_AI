import os
from collections.abc import Callable
from typing import Protocol

from google.auth.credentials import AnonymousCredentials
from google.cloud import firestore

from app.config import Settings
from app.errors import AppError
from app.models.schemas import Assessment

Mutation = Callable[[Assessment | None], Assessment | None]


class AssessmentRepository(Protocol):
    def get(self, device_id: str, assessment_id: str) -> Assessment | None: ...
    def latest(self, device_id: str) -> Assessment | None: ...
    def mutate(self, device_id: str, assessment_id: str, change: Mutation) -> Assessment | None:
        """Atomically read, apply a pure callback, and write/delete one assessment."""
        ...

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

    def mutate(self, device_id: str, assessment_id: str, change: Mutation) -> Assessment | None:
        ref = self.collection(device_id).document(assessment_id)

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

    def close(self):
        self.client.close()
