"""Managed end-user identity. Internal routes continue using service OIDC."""

import base64

import firebase_admin
from firebase_admin import auth, credentials

from app.errors import AppError


def owner_key(uid: str) -> str:
    """Opaque Firebase UIDs may contain path separators; encode one path component."""
    return base64.urlsafe_b64encode(uid.encode()).decode().rstrip("=")


class FirebaseIdentity:
    def __init__(self, settings):
        self.app = firebase_admin.initialize_app(
            credentials.ApplicationDefault(),
            {"projectId": settings.google_cloud_project},
            name=f"home-safety-{id(self)}",
        )

    def verify(self, token):
        try:
            claims = auth.verify_id_token(token, app=self.app, check_revoked=True)
            if claims.get("firebase", {}).get("sign_in_provider") != "password":
                raise ValueError("Account sign-in required")
            return claims
        except (
            auth.InvalidIdTokenError,
            auth.RevokedIdTokenError,
            auth.UserDisabledError,
            auth.UserNotFoundError,
            ValueError,
        ):
            raise AppError(401, "unauthorized", "Sign in again to continue.") from None

    def revoke(self, uid):
        try:
            auth.revoke_refresh_tokens(uid, app=self.app)
        except auth.UserNotFoundError:
            pass

    def delete(self, uid):
        try:
            auth.delete_user(uid, app=self.app)
        except auth.UserNotFoundError:
            pass

    def close(self):
        firebase_admin.delete_app(self.app)
