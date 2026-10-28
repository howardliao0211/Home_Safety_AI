"""Run independently from the API: python -m app.annotations.local_worker."""

import time

from app.annotations.provider import MuseHighlightProvider
from app.annotations.service import AnnotationService
from app.config import Settings
from app.storage.photos import GCSPhotoStore
from app.storage.repository import FirestoreRepository


def main():
    settings = Settings()
    if settings.environment != "local":
        raise SystemExit("Use Cloud Tasks in production.")
    if settings.model_provider != "muse" or not settings.muse_segmentation_model.strip():
        raise SystemExit("Configure MUSE and MUSE_SEGMENTATION_MODEL before running the worker.")
    records, photos = FirestoreRepository(settings), GCSPhotoStore(settings)
    service = AnnotationService(records, photos, MuseHighlightProvider(settings))
    try:
        while True:
            service.recover()
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        records.close()
        photos.close()


if __name__ == "__main__":
    main()
