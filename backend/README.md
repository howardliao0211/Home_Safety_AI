# Backend development

FastAPI implements photo assessments, focused follow-ups, user-requested photo
reviews, finding status/checklist actions, latest-assessment retrieval, retained
evidence, and retryable deletion. Groq is the development model provider. The
Expo frontend currently uses its preview service; connecting its state and API
client to this backend is separate work.

## Start locally

Requirements: Python 3.10+, [uv](https://docs.astral.sh/uv/), Docker Engine with
Compose, and your Groq credentials. Java and gcloud run inside the Firestore
container, so host installations are unnecessary. Run from the repository root:

```bash
docker compose -f backend/compose.yaml up -d
cd backend
uv sync --extra dev --locked
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

Open `http://127.0.0.1:8000/docs` for the interactive API and
`http://127.0.0.1:8000/healthz` for liveness. The first startup needs both emulator
containers running. Inspect startup with `docker compose -f backend/compose.yaml
logs --tail=30` from the repo root. A daemon/socket permission error means Docker
needs to be made accessible in your development environment.

The backend loads the root `.env`, then optional `backend/.env`; actual process
environment variables take precedence. Your existing `GROQ_API_KEY` and
`GROQ_MODEL` are sufficient, with `MODEL_PROVIDER=groq` and local storage as
defaults. Keep the key server-side. See [`.env.example`](../.env.example) for
configuration; preserve your existing `.env` when adding settings.
`GROQ_API_KEY` must be a Groq API key. `GROQ_MODEL` is the model hosted on Groq,
for example `qwen/qwen3.8-27b`. The adapter sends requests to
`https://api.groq.com/openai/v1/chat/completions`.

Local mode always uses storage emulators, with anonymous credentials. Defaults:

| Setting | Local default |
| --- | --- |
| `MODEL_PROVIDER` | `groq` |
| `MODEL_TIMEOUT_SECONDS` | `90` (allowed 1–120) |
| `GOOGLE_CLOUD_PROJECT` | `home-safety-local` |
| `FIRESTORE_DATABASE_ID` | `(default)` |
| `PHOTOS_BUCKET` | `home-safety-local-photos` |
| `FIRESTORE_EMULATOR_HOST` | `127.0.0.1:8080` |
| `STORAGE_EMULATOR_HOST` | `http://127.0.0.1:4443` |

The local bucket is created automatically. Emulator ports bind only to loopback.
Compose pins the Google Cloud SDK emulator image and fake-gcs-server 1.52.3 by
digest. Named volumes retain data. A small launcher calls Firestore's export API
before stopping Java, commits a snapshot manifest only after export succeeds,
and imports that snapshot on startup. It preserves the previous snapshot if
export fails. From the repo root:

```bash
docker compose -f backend/compose.yaml stop
docker compose -f backend/compose.yaml start
```

Allow the configured shutdown grace period. A forced kill can lose Firestore
changes since its last export. `down` preserves named volumes; `down -v` removes
all local assessments and photos. This local setup preserves the production
Firestore/GCS decision in [ADR 0001](../docs/adr/0001-managed-demo-storage.md).
Keep the local project set to `home-safety-local` and database to `(default)` for
the documented emulator/test setup. If changing the project, configure
`GOOGLE_CLOUD_PROJECT` identically for Compose and the backend; snapshots export
that configured project's default database. Put shared settings in the root
`.env` or process environment, which both tools read.

## HTTP contract

All assessment endpoints require `X-Device-ID`, a persistent client-generated
UUID for the app installation. Resource IDs are UUIDs. Device scoping applies
to every read, write, photo download, and deletion; it is not authenticated
identity. If `DEMO_BEARER_TOKEN` is configured, send `Authorization: Bearer <token>`
on every API request, including health checks. OpenAPI docs contain no secrets.

Responses use snake_case fields. The mobile preview currently uses camelCase;
its future API client needs an explicit mapping and server-owned state handling.

| Method and path | Input / behavior |
| --- | --- |
| `GET /healthz` | Liveness only; no model call or storage readiness guarantee |
| `POST /v1/assessments` | Multipart `assessment_id`, `photo`, optional `profiles` JSON array, `household_context`; retains upload and returns `ready` |
| `GET /v1/assessments/latest` | Latest assessment for this device; skips deletions in progress; 404 if none |
| `GET /v1/assessments/{aid}` | Current state, findings and linked submissions |
| `POST /v1/assessments/{aid}/analyze` | Runs initial analysis; same endpoint manually retries failures |
| `PATCH /v1/assessments/{aid}/findings/{fid}` | JSON `status`: `open`, `resolved`, or `dismissed`, optional `note` (omitted preserves the current note; empty clears it) |
| `POST /v1/assessments/{aid}/findings/{fid}/skip-follow-up` | Skips the agent's request |
| `POST /v1/assessments/{aid}/findings/{fid}/submissions` | Multipart `submission_id`, `kind` (`follow-up` or `review`), optional `text` and `photo`; returns retained `ready` submission |
| `POST /v1/assessments/{aid}/findings/{fid}/submissions/{sid}/analyze` | Runs or manually retries this linked check |
| `GET /v1/assessments/{aid}/photos/{pid}` | Private photo bytes after device scoping |
| `DELETE /v1/assessments/{aid}` | Removes all associated photos, then the document; repeat until 204 on partial failure |

Profiles are `Older adult`, `Child`, `Baby`, `Pet`, including multiple profiles;
`[]` selects a general assessment. Uploads accept decoded JPEG/PNG/WebP under
10 MiB and 20 megapixels. The backend applies EXIF orientation, resizes to at
most 1600 pixels per side, and stores a JPEG without metadata. IDs and photo
references are generated and checked by the server.

For example, from the repo root in another terminal (with a running backend):

```bash
device_id=$(python3 -c 'import uuid; print(uuid.uuid4())')
assessment_id=$(python3 -c 'import uuid; print(uuid.uuid4())')
curl --fail-with-body http://127.0.0.1:8000/v1/assessments \
  -H "X-Device-ID: $device_id" \
  -F "assessment_id=$assessment_id" \
  -F 'profiles=["Older adult","Baby","Pet"]' \
  -F 'photo=@mobile/assets/rooms/living-room.jpg'
curl --fail-with-body -X POST \
  "http://127.0.0.1:8000/v1/assessments/$assessment_id/analyze" \
  -H "X-Device-ID: $device_id"
```

Add your bearer header if configured. Reuse the same device ID on subsequent
requests. A real analysis sends the photo to Groq and consumes your quota.

## Retry and state rules

Generate assessment and submission UUIDs once before uploading. Resending the
same ID and input reuses the retained record; changed input with the same ID
returns 409. After a successful upload, analysis requires only the analysis
endpoint, including manual retries. Completed analysis is idempotent and never
calls the model again. Failed uploads return 503 and require resending the
original input with its original ID.

Analysis failures return 502 with an `error` object containing `code`, `message`,
and `request_id`. Credential rejection uses `model_credentials_rejected`; quota
or rate limiting uses `model_rate_limited`, with actionable messages. Fetch the assessment to display the failed operation and Retry
action. Initial failures have `status=failed`, never a successful empty result.
Linked failures retain the existing findings, submitted text and uploaded photo.
There are no automatic model retries or provider fallbacks. Logs contain safe
diagnostic categories, upstream status codes, exception types/code locations,
and operation/resource/request identifiers; credentials and payloads are omitted.

Mutations serialize per assessment through a transactional lease. Concurrent
mutations return 409 `busy`. If a worker exits during a call, retry manually
after the five-minute lease expires; GET may show `running` until then. Lease
tokens prevent a superseded worker from overwriting a newer operation.

The model can propose at most 12 findings. Each finding is one checklist item,
with one optional agent-initiated follow-up; a submitted follow-up is retried by
its existing ID. A skipped or consumed follow-up cannot be replaced. New photo
reviews remain available independently. The controller preserves the user's
status and note during every model revision. Only the status endpoint can
resolve, dismiss, or reopen a finding.

The MVP stores one bounded Firestore document per assessment: at most 20 linked
submissions per finding, 3,000 characters per text field (shorter title/action
limits), and a 750 KB serialized document ceiling. Capacity errors return 409.
Larger histories would require moving submissions to separate documents.

Deletion marks the assessment as deleting before touching GCS. Subsequent reads,
uploads, and model calls are blocked. If either storage operation fails, repeat
DELETE with the same device/resource IDs. An active operation can delay deletion
until it finishes or its lease expires. Photos are private and returned with
`Cache-Control: no-store` through the API.

## Switching to Muse

The workflow depends only on `ModelProvider.generate` in
[`app/models/providers/base.py`](app/models/providers/base.py): system instructions,
plain context, up to two private image payloads, and a provider-neutral output
schema. Prompts live in `app/assessments/prompts/`; the controller validates
every response with Pydantic before applying it to stored state. Provider/model
provenance is recorded per analysis attempt.

Once the organisers supply the real Muse API contract:

1. Implement a Muse adapter with `name`, `model`, `generate`, and `close`. Map its
   image/authentication/response conventions to the shared interface. Return JSON
   data or a `ModelError` containing safe diagnostics; keep retries disabled.
2. Add Muse credential/model settings and register its adapter in `build_provider`
   in `app/models/providers/factory.py`. Extend provider contract tests using its
   actual response format.
3. Configure `MODEL_PROVIDER=muse` and backend-only Muse credentials, then run
   the same workflow and real-photo smoke checks.

Routes, prompts, domain state and storage stay shared. Selecting Muse today fails
at startup with a clear pending-contract message. No endpoint, model ID, or
OpenAI-compatible contract is assumed for Muse. Groq's photo/strict JSON behavior
is documented in its [model reference](https://console.groq.com/docs/model/qwen/qwen3.8-27b)
and [structured output guide](https://console.groq.com/docs/structured-outputs).

## Verification

From `backend/`:

```bash
uv run ruff check .
uv run ruff format --check .
uv run pytest -q
RUN_EMULATOR_TESTS=1 uv run pytest tests/test_emulators.py -q
RUN_EMULATOR_RESTART_TESTS=1 uv run pytest tests/test_emulator_restart.py -q
```

The default suite uses in-memory test doubles, exercises the real HTTP routes,
and mocks Groq's HTTP boundary. Emulator checks use actual Firestore/GCS clients,
retained evidence, linked revisions, status persistence and deletion. The restart
check actually stops/starts both local storage containers, verifying their named
volumes and the Firestore export/import path. A separate
opt-in check makes up to two real Groq calls using the bundled room photo and
cleans its local records afterward:

```bash
RUN_EMULATOR_TESTS=1 RUN_LIVE_MODEL_TESTS=1 \
  uv run pytest tests/test_emulators.py::test_real_groq_photo_assessment_and_review -q
```

For a small development quota, add `LIVE_MODEL_INTERVAL_SECONDS=60` to space
the assessment and review requests. This only paces the opt-in smoke test;
the application still requires an explicit manual retry after any failed call.

These verify integration and state behavior, not hazard-detection accuracy.

## Production configuration

Set `ENVIRONMENT=production`, the real `GOOGLE_CLOUD_PROJECT`,
`FIRESTORE_DATABASE_ID`, `PHOTOS_BUCKET`, model settings, and `DEMO_BEARER_TOKEN`.
Remove both emulator environment variables. Production rejects emulator endpoints
and requires a bearer token. Google clients use Application Default Credentials
from the Cloud Run service account; Terraform manages storage provisioning and
private bucket configuration. The container binds `0.0.0.0:$PORT` and runs as a
non-root user. Production disables `/docs`, `/redoc` and `/openapi.json`.

Build locally with `docker build -t home-safety-backend:dev backend` from the repo
root. See [deploy/README.md](../deploy/README.md) for separate Terraform provisioning,
Secret Manager initialization, Cloud Run release verification and rollback.
