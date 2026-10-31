"""Run independently from the API: python -m app.annotations.local_worker."""

import threading
import time
from concurrent.futures import ThreadPoolExecutor, wait

from app.accounts import AccountDeletion
from app.annotations.provider import MuseHighlightProvider
from app.annotations.service import AnnotationService
from app.assessments.chat import ChatService
from app.assessments.service import AssessmentService
from app.auth import FirebaseIdentity
from app.config import Settings
from app.models.providers.factory import build_provider
from app.storage.photos import GCSPhotoStore
from app.storage.repository import FirestoreRepository

# Admits every finding of one assessment (the 12-finding limit) at once.
CONCURRENCY = 12


class LocalWorker:
    """Claims each pending attempt independently, mirroring Cloud Tasks deliveries."""

    def __init__(self, service, concurrency=CONCURRENCY, chat=None):
        self.service = service
        self.chat = chat
        self.executor = ThreadPoolExecutor(concurrency, thread_name_prefix="highlight")
        self.lock = threading.Lock()
        self.running = {}

    def tick(self):
        self.service.reap_assets()
        jobs = [(self.service.work, item) for item in self.service.pending()]
        if self.chat:
            # Same claims as Cloud Tasks deliveries: expiry, then queued attempts.
            self.chat.recover()
            jobs += [(self.chat.work, item) for item in self.chat.pending()]
        for work, item in jobs:
            with self.lock:
                if item in self.running:
                    continue
                future = self.executor.submit(work, *item)
                self.running[item] = future
            future.add_done_callback(lambda _, item=item: self._finished(item))

    def _finished(self, item):
        with self.lock:
            self.running.pop(item, None)

    def drain(self, timeout=None):
        with self.lock:
            futures = list(self.running.values())
        wait(futures, timeout=timeout)

    def close(self):
        self.executor.shutdown(wait=True, cancel_futures=True)


def main():
    settings = Settings()
    if settings.environment != "local":
        raise SystemExit("Use Cloud Tasks in production.")
    records, photos = FirestoreRepository(settings), GCSPhotoStore(settings)
    identity = FirebaseIdentity(settings)
    accounts = AccountDeletion(records, photos, identity)
    photos.account_guard = records.accounts.require_active
    provider = (
        MuseHighlightProvider(settings)
        if settings.model_provider == "muse" and settings.muse_segmentation_model.strip()
        else None
    )
    model = build_provider(settings)
    chat = ChatService(AssessmentService(records, photos, model))
    worker = LocalWorker(AnnotationService(records, photos, provider), chat=chat)
    try:
        while True:
            accounts.recover()
            worker.tick()
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        worker.close()
        model.close()
        identity.close()
        records.close()
        photos.close()


if __name__ == "__main__":
    main()
