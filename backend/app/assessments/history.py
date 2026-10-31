"""Account-bound pagination and the lightweight history response."""

import base64
import binascii
import json
from datetime import datetime
from uuid import UUID

from app.auth import owner_key
from app.errors import AppError
from app.models.schemas import Assessment


def encode_cursor(owner_uid: str, assessment: Assessment) -> str:
    value = [owner_key(owner_uid), assessment.created_at.isoformat(), assessment.id]
    return base64.urlsafe_b64encode(json.dumps(value).encode()).decode()


def decode_cursor(cursor: str, owner_uid: str) -> tuple[datetime, str]:
    try:
        scope, timestamp, assessment_id = json.loads(
            base64.b64decode(cursor, altchars=b"-_", validate=True)
        )
        created_at = datetime.fromisoformat(timestamp)
        if (
            scope != owner_key(owner_uid)
            or created_at.tzinfo is None
            or not isinstance(assessment_id, str)
        ):
            raise ValueError()
        UUID(assessment_id)
        return created_at, assessment_id
    except (ValueError, TypeError, binascii.Error, UnicodeDecodeError):
        raise AppError(
            422, "invalid_cursor", "Refresh history to load these assessments."
        ) from None


def history_item(assessment: Assessment) -> dict:
    return {
        "id": assessment.id,
        "title": assessment.title,
        "created_at": assessment.created_at.isoformat(),
        "status": assessment.status,
        "open_count": sum(f.status == "open" for f in assessment.findings)
        if assessment.status == "complete"
        else None,
        "photo": {"id": assessment.photo.id, "uploaded": assessment.photo.uploaded},
    }
