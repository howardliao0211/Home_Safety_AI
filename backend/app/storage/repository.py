import os
import time
from collections.abc import Callable
from typing import Protocol

from google.api_core.exceptions import Aborted, FailedPrecondition, NotFound
from google.auth.credentials import AnonymousCredentials
from google.cloud import firestore

from app.accounts import AccountStore, active
from app.auth import owner_key
from app.config import Settings
from app.errors import AppError
from app.models.schemas import Assessment

Mutation = Callable[[Assessment | None], Assessment | None]


class AssessmentRepository(Protocol):
    def get(self, owner_uid: str, assessment_id: str) -> Assessment | None: ...
    def latest(self, owner_uid: str) -> Assessment | None: ...
    def mutate(
        self, owner_uid: str, assessment_id: str, change: Mutation, *, deadline: float | None = None
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

        self.accounts = AccountStore(self.client)

    def collection(self, owner_uid: str):
        return (
            self.client.collection("users").document(owner_key(owner_uid)).collection("assessments")
        )

    def get(self, owner_uid: str, assessment_id: str) -> Assessment | None:
        self.accounts.require_active(owner_uid)
        snapshot = self.collection(owner_uid).document(assessment_id).get(timeout=10)
        return Assessment.model_validate(snapshot.to_dict()) if snapshot.exists else None

    def latest(self, owner_uid: str) -> Assessment | None:
        self.accounts.require_active(owner_uid)
        # Deleted/in-progress deletions cannot hide the previous latest assessment.
        query = self.collection(owner_uid).order_by("created_at", direction="DESCENDING")
        for snapshot in query.stream(timeout=10):
            result = Assessment.model_validate(snapshot.to_dict())
            if not result.deleting:
                return result
        return None

    def mutate(
        self, owner_uid: str, assessment_id: str, change: Mutation, *, deadline: float | None = None
    ) -> Assessment | None:
        ref = self.collection(owner_uid).document(assessment_id)
        if deadline is not None:
            return self._bounded_mutate(owner_uid, ref, change, deadline)

        @firestore.transactional
        def run(transaction):
            active(self.accounts.ref(owner_uid).get(transaction=transaction, timeout=10).to_dict())
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

    def _bounded_mutate(self, owner_uid, ref, change, deadline):
        """Account fence and publication commit atomically within the work budget."""

        def left():
            seconds = deadline - time.monotonic()
            if seconds <= 0:
                raise TimeoutError()
            return seconds

        while True:
            transaction = self.client.transaction(max_attempts=1)
            # The decorator does not expose begin/commit deadlines. Use the SDK
            # transport with retries disabled for every phase of this transaction.
            transaction._id = self.client._firestore_api.begin_transaction(
                request={"database": self.client._database_string}, timeout=left(), retry=None
            ).transaction
            committed = False
            try:
                active(
                    self.accounts.ref(owner_uid)
                    .get(transaction=transaction, timeout=left(), retry=None)
                    .to_dict()
                )
                snapshot = ref.get(transaction=transaction, timeout=left(), retry=None)
                previous = (
                    Assessment.model_validate(snapshot.to_dict()) if snapshot.exists else None
                )
                states = {j.id: j.state for j in previous.annotations} if previous else {}
                updated = change(previous)
                if updated is None:
                    return None
                check_size(updated)
                payload = updated.model_dump(mode="python")
                publishing = [
                    j.id
                    for j in updated.annotations
                    if j.state == "ready" and states.get(j.id) != "ready"
                ]
                for annotation_id in publishing:
                    payload["annotation_commits"][annotation_id] = firestore.SERVER_TIMESTAMP
                transaction.update(
                    ref,
                    payload,
                    option=self.client.write_option(last_update_time=snapshot.update_time),
                )
                result = self.client._firestore_api.commit(
                    request={
                        "database": self.client._database_string,
                        "writes": transaction._write_pbs,
                        "transaction": transaction.id,
                    },
                    timeout=left(),
                    retry=None,
                ).write_results[0]
                committed = True
                for annotation_id in publishing:
                    updated.annotation_commits[annotation_id] = result.update_time
                return updated
            except (Aborted, FailedPrecondition):
                left()
            except NotFound:
                return change(None)
            finally:
                if not committed:
                    self.client._firestore_api.rollback(
                        request={
                            "database": self.client._database_string,
                            "transaction": transaction.id,
                        },
                        timeout=max(0.01, min(1, deadline - time.monotonic())),
                        retry=None,
                    )

    def annotation_pending(self):
        # One-field collection-group index, provisioned in Terraform.
        query = self.client.collection_group("assessments").where(
            filter=firestore.FieldFilter("annotation_dispatch_pending", "==", True)
        )
        return [
            Assessment.model_validate(s.to_dict())
            for s in query.stream(timeout=10)
            if s.reference.path.startswith("users/")
        ]

    def close(self):
        self.client.close()
