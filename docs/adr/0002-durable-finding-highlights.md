# Dispatch finding highlights with Cloud Tasks and Firestore leases

Finding highlights run independently of safety analysis and mobile navigation.
Cloud Tasks delivers authenticated HTTP work to Cloud Run; an independent Cloud
Scheduler sweep recovers persisted dispatch intent. Firestore is authoritative:
annotation attempts, evidence revisions, and per-assessment claims share an atomic
assessment document. A started attempt expires after 30 seconds and is never
restarted by duplicate delivery or dispatch recovery. Only a manual retry creates
a new attempt. An in-process API background task cannot survive request-bound
Cloud Run CPU or instance shutdown, so it is insufficient here.

Masks share the private GCS assessment prefix and retryable deletion from ADR
0001. Publication checks revision, deletion state, lease identity, and expiry.
Asset identity is reserved before upload, and recovery removes orphan masks,
including uploads that race deletion after the assessment document disappears.
The independent local worker uses the same transitions with the storage emulators.
Embedding bounded metadata/history keeps queue claims atomic; the existing
Firestore document size guard and a 120-attempt limit bound demo retention.

Annotation writes use update-time compare-and-set preconditions with SDK retries
disabled and explicit remaining-budget timeouts. A sibling map stores server-side
publication timestamps (Firestore cannot transform values inside annotation
arrays), so a late commit is failed before client metadata or masks are served.
SAM parsing/raster decoding and overlay construction run in killable processes,
so synchronous mask work cannot prevent deadline cancellation.
