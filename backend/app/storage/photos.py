import hashlib
import io
import warnings
from typing import Protocol

from google.api_core.exceptions import NotFound
from google.auth.credentials import AnonymousCredentials
from google.cloud import storage
from PIL import Image, ImageOps, UnidentifiedImageError

from app.auth import owner_key
from app.config import Settings
from app.errors import AppError
from app.models.schemas import Photo

MAX_UPLOAD_BYTES = 10 * 1024 * 1024
Image.MAX_IMAGE_PIXELS = 20_000_000


def prepare_photo(data: bytes) -> tuple[Photo, bytes]:
    if not data or len(data) > MAX_UPLOAD_BYTES:
        raise AppError(413, "photo_size", "Choose a JPEG, PNG, or WebP photo smaller than 10 MiB.")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as source:
                if source.format not in {"JPEG", "PNG", "WEBP"}:
                    raise ValueError("Unsupported image")
                source.load()
                image = ImageOps.exif_transpose(source).convert("RGB")
                image.thumbnail((1600, 1600))
                output = io.BytesIO()
                image.save(output, format="JPEG", quality=85)
                clean = output.getvalue()
    except (
        UnidentifiedImageError,
        OSError,
        ValueError,
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
    ):
        raise AppError(
            422, "invalid_photo", "Use a readable JPEG, PNG, or WebP under 20 megapixels."
        ) from None
    return Photo(content_type="image/jpeg", sha256=hashlib.sha256(clean).hexdigest()), clean


class PhotoStore(Protocol):
    def put(
        self, owner_uid: str, assessment_id: str, photo: Photo, data: bytes, *, timeout: float = 20
    ) -> None: ...
    def get(
        self, owner_uid: str, assessment_id: str, photo: Photo, *, timeout: float = 20
    ) -> bytes: ...
    def delete(self, owner_uid: str, assessment_id: str, photo: Photo) -> None: ...
    def delete_assessment(self, owner_uid: str, assessment_id: str) -> None: ...
    def annotation_assets(self): ...
    def room_concept_assets(self): ...
    def close(self) -> None: ...


class GCSPhotoStore:
    def __init__(self, settings: Settings):
        self.client = storage.Client(
            project=settings.google_cloud_project,
            credentials=AnonymousCredentials() if settings.storage_emulator_host else None,
            client_options={"api_endpoint": settings.storage_emulator_host}
            if settings.storage_emulator_host
            else None,
        )
        self.account_guard = None
        self.bucket = self.client.bucket(settings.photos_bucket)
        if settings.storage_emulator_host:
            # Local emulator only. Production buckets are managed by Terraform.
            from google.api_core.exceptions import Conflict

            try:
                self.client.create_bucket(self.bucket, retry=None, timeout=10)
            except Conflict:
                pass

    @staticmethod
    def prefix(owner_uid: str, assessment_id: str) -> str:
        return f"users/{owner_key(owner_uid)}/assessments/{assessment_id}/"

    def blob(self, owner_uid: str, assessment_id: str, photo: Photo):
        return self.bucket.blob(self.prefix(owner_uid, assessment_id) + photo.id)

    def put(
        self, owner_uid: str, assessment_id: str, photo: Photo, data: bytes, *, timeout: float = 20
    ):
        if self.account_guard:
            self.account_guard(owner_uid)
        self.blob(owner_uid, assessment_id, photo).upload_from_string(
            data, content_type=photo.content_type, timeout=timeout, retry=None
        )
        if self.account_guard:
            try:
                self.account_guard(owner_uid)
            except AppError:
                self.delete(owner_uid, assessment_id, photo)
                raise

    def get(
        self, owner_uid: str, assessment_id: str, photo: Photo, *, timeout: float = 20
    ) -> bytes:
        return self.blob(owner_uid, assessment_id, photo).download_as_bytes(
            timeout=timeout, retry=None
        )

    def delete(self, owner_uid: str, assessment_id: str, photo: Photo):
        try:
            self.blob(owner_uid, assessment_id, photo).delete(timeout=10, retry=None)
        except NotFound:
            pass

    def delete_assessment(self, owner_uid: str, assessment_id: str):
        for blob in self.client.list_blobs(
            self.bucket, prefix=self.prefix(owner_uid, assessment_id), timeout=20, retry=None
        ):
            try:
                blob.delete(timeout=20, retry=None)
            except NotFound:
                pass

    def delete_account(self, uid):
        for blob in self.client.list_blobs(
            self.bucket, prefix=f"users/{owner_key(uid)}/", timeout=20, retry=None
        ):
            try:
                blob.delete(timeout=20, retry=None)
            except NotFound:
                pass

    def annotation_assets(self):
        yield from (
            (owner, aid, key.removeprefix("annotation-"))
            for owner, aid, key in self._generated_assets("annotation-")
        )

    def room_concept_assets(self):
        yield from self._generated_assets("room-concept-")

    def _generated_assets(self, prefix):
        for blob in self.client.list_blobs(self.bucket, prefix="users/", timeout=10, retry=None):
            parts = blob.name.split("/")
            if (
                len(parts) == 5
                and parts[0] == "users"
                and parts[2] == "assessments"
                and parts[4].startswith(prefix)
            ):
                import base64

                uid = base64.urlsafe_b64decode(parts[1] + "=" * (-len(parts[1]) % 4)).decode()
                yield uid, parts[3], parts[4]

    def close(self):
        self.client.close()
