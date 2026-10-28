"""Durable account tombstones and session-independent deletion receipts."""

import hashlib
import hmac
import logging
import secrets
import time
from uuid import UUID, uuid4

from google.cloud import firestore

from app.auth import owner_key
from app.errors import AppError

logger = logging.getLogger(__name__)
RECEIPT_SECONDS = 7 * 24 * 3600
# Exceeds every model/upload/worker deadline; subsequent sweeps remove late objects.
QUIET_SECONDS = 330


def active(record):
    if record and record.get("state") in {"deleting", "deleted"}:
        raise AppError(403, "account_deleting", "Account deletion is in progress.")


class AccountStore:
    def __init__(self, client):
        self.client = client

    def ref(self, uid):
        return self.client.collection("users").document(owner_key(uid))

    def require_active(self, uid):
        active(self.ref(uid).get(timeout=10).to_dict())

    def begin(self, uid):
        operation, secret = str(uuid4()), secrets.token_urlsafe(32)
        receipt = self.client.collection("deletion_operations").document(operation)
        user = self.ref(uid)
        timestamp = time.time()

        @firestore.transactional
        def accept(transaction):
            previous = user.get(transaction=transaction, timeout=10).to_dict() or {}
            if previous.get("state") not in {"deleting", "deleted"}:
                transaction.set(
                    user, {"owner_uid": uid, "state": "deleting", "accepted_at": timestamp}
                )
            transaction.set(
                receipt,
                {
                    "owner_uid": uid,
                    "digest": hashlib.sha256(secret.encode()).hexdigest(),
                    "expires_at": timestamp + RECEIPT_SECONDS,
                },
            )

        accept(self.client.transaction())
        return {
            "receipt": operation + "." + secret,
            "status": "pending",
            "expires_at": timestamp + RECEIPT_SECONDS,
        }

    def status(self, receipt):
        try:
            operation, secret = receipt.split(".", 1)
            UUID(operation)
        except (ValueError, AttributeError):
            raise AppError(404, "not_found", "Deletion operation not found.") from None
        record = (
            self.client.collection("deletion_operations")
            .document(operation)
            .get(timeout=10)
            .to_dict()
        )
        if not record or not hmac.compare_digest(
            record["digest"], hashlib.sha256(secret.encode()).hexdigest()
        ):
            raise AppError(404, "not_found", "Deletion operation not found.")
        if record["expires_at"] <= time.time():
            raise AppError(
                410,
                "receipt_expired",
                "Receipt expired. Sign in and reauthenticate to recover deletion status if the account still exists.",
            )
        user = self.ref(record["owner_uid"]).get(timeout=10).to_dict() or {}
        return {"status": "complete" if user.get("state") == "deleted" else "pending"}


class AccountDeletion:
    def __init__(self, records, photos, identity):
        self.records, self.photos, self.identity = records, photos, identity
        self.accounts = records.accounts

    def begin(self, claims):
        age = time.time() - claims.get("auth_time", 0)
        if not 0 <= age <= 300:
            raise AppError(
                403,
                "reauthentication_required",
                "Enter your password again to delete your account.",
            )
        receipt = self.accounts.begin(claims["uid"])
        # The durable tombstone already blocks every device even if revocation fails.
        try:
            self.identity.revoke(claims["uid"])
        except Exception as exc:
            logger.error("account_revoke_failed category=%s", type(exc).__name__)
        return receipt

    def recover(self):
        # Retain tombstones and sweep completed accounts too: a paused uploader
        # must never permanently recreate objects after cleanup.
        query = self.accounts.client.collection("users").where(
            filter=firestore.FieldFilter("state", "in", ["deleting", "deleted"])
        )
        for snapshot in query.stream(timeout=20):
            record = snapshot.to_dict()
            uid = record["owner_uid"]
            try:
                self.photos.delete_account(uid)
                if time.time() < record["accepted_at"] + QUIET_SECONDS:
                    continue
                for assessment in snapshot.reference.collection("assessments").stream(timeout=20):
                    self.accounts.client.recursive_delete(assessment.reference)
                self.photos.delete_account(uid)
                if record["state"] != "deleted":
                    self.identity.delete(uid)
                    snapshot.reference.update({"state": "deleted"}, timeout=10)
            except Exception as exc:
                logger.error("account_cleanup_failed category=%s", type(exc).__name__)
