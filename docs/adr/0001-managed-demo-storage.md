# Use Firestore and GCS for the demo backend

Use Firestore Standard in Native mode for assessment, finding, follow-up, and
checklist data, and a private GCS bucket for photos. This supersedes the original
SQLite and VM data-disk plan: the user prefers managed services similar to DynamoDB
and S3, and data should survive VM replacement. Only FastAPI accesses these stores
using its VM service account; the mobile app continues using the backend API.

Firestore and GCS do not share a transaction. Assessment deletion must be retryable
across both stores, including partial failures. Photo versioning and soft delete
are disabled by explicit user choice, trading accidental-deletion recovery for
removal without recoverable object versions. Database/bucket destruction guards
were initially enabled, then removed at the user's explicit request to allow
straightforward Terraform teardown, including deletion of bucket contents.
