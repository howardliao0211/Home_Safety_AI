import hashlib
import io
import warnings
from typing import Protocol

from google.api_core.exceptions import NotFound
from google.auth.credentials import AnonymousCredentials
from google.cloud import storage
from PIL import Image, ImageOps, UnidentifiedImageError

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
    def put(self, device_id: str, assessment_id: str, photo: Photo, data: bytes) -> None: ...
    def get(self, device_id: str, assessment_id: str, photo: Photo) -> bytes: ...
    def delete_assessment(self, device_id: str, assessment_id: str) -> None: ...
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
        self.bucket = self.client.bucket(settings.photos_bucket)
        if settings.storage_emulator_host:
            # Local emulator only. Production buckets are managed by Terraform.
            from google.api_core.exceptions import Conflict

            try:
                self.client.create_bucket(self.bucket, retry=None, timeout=10)
            except Conflict:
                pass

    @staticmethod
    def prefix(device_id: str, assessment_id: str) -> str:
        return f"devices/{device_id}/assessments/{assessment_id}/"

    def blob(self, device_id: str, assessment_id: str, photo: Photo):
        return self.bucket.blob(self.prefix(device_id, assessment_id) + photo.id)

    def put(self, device_id: str, assessment_id: str, photo: Photo, data: bytes):
        self.blob(device_id, assessment_id, photo).upload_from_string(
            data, content_type=photo.content_type, timeout=20, retry=None
        )

    def get(self, device_id: str, assessment_id: str, photo: Photo) -> bytes:
        return self.blob(device_id, assessment_id, photo).download_as_bytes(timeout=20, retry=None)

    def delete_assessment(self, device_id: str, assessment_id: str):
        for blob in self.client.list_blobs(
            self.bucket, prefix=self.prefix(device_id, assessment_id), timeout=20, retry=None
        ):
            try:
                blob.delete(timeout=20, retry=None)
            except NotFound:
                pass

    def close(self):
        self.client.close()
