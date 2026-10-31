# Backend development

FastAPI implements photo assessments, saved finding chat, and legacy user-requested photo
reviews, finding status/checklist actions, latest-assessment retrieval, retained
evidence, and retryable deletion. Muse is the demo model provider; Groq remains an explicit development option. The
Expo frontend connects to this API by default; explicit preview mode remains
available without a backend.

## Start locally

Requirements: Python 3.10+, [uv](https://docs.astral.sh/uv/), Docker Engine with
Compose, and your Meta Muse credentials. Java and gcloud run inside the Firestore
container, so host installations are unnecessary. Run from the repository root:

```bash
docker compose -f backend/compose.yaml up -d
cd backend
uv sync --extra dev --locked
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

Open `http://127.0.0.1:8000/docs` for the interactive API and
`http://127.0.0.1:8000/health` for liveness. The first startup needs both emulator
containers running. Inspect startup with `docker compose -f backend/compose.yaml
logs --tail=30` from the repo root. A daemon/socket permission error means Docker
needs to be made accessible in your development environment.

The backend loads the root `.env`, then optional `backend/.env`; actual process
environment variables take precedence. Configure the backend-only settings:

```dotenv
MODEL_PROVIDER=muse
MUSE_API_KEY=your-meta-api-key
MUSE_MAIN_MODEL=muse-wonder-1.0
```

Keep your existing `.env`; add or update these names without copying credentials
into the frontend. The supplied Meta sample calls the key `MODEL_API_KEY`; this
application reads `MUSE_API_KEY` instead. The adapter uses bearer authentication
at `https://api.meta.ai/v1/responses`. It submits inline base64 photos, requests
strict JSON through `text.format`, uses `stream=false` and `store=false`, and
validates model output before storing it. It does not create Meta-managed
conversation history; this is not a guarantee about other provider retention.

To use Groq explicitly, set `MODEL_PROVIDER=groq`, `GROQ_API_KEY`, and
`GROQ_MODEL`. Its endpoint remains
`https://api.groq.com/openai/v1/chat/completions`. There is no automatic fallback.
With no provider setting the code retains the Groq default for existing setups;
the example environment selects Muse explicitly.

Local mode always uses storage emulators, with anonymous credentials. Defaults:

| Setting | Local default |
| --- | --- |
| `MODEL_PROVIDER` | `groq` if unset; `.env.example` selects `muse` |
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

Assessment endpoints require `Authorization: Bearer <Firebase ID token>` for a
verified email/password account. Resource IDs remain UUIDs; Firebase UIDs are
opaque and server-controlled. Device headers have no authorization effect.
`/health` is public liveness. Internal workers use service OIDC.
See [account setup and deletion](../docs/authentication.md).

Responses use snake_case fields. The mobile API client maps these to its
camelCase domain model and uses the server's saved assessment state.

For local Expo web, CORS allows `http://localhost:8081` and
`http://127.0.0.1:8081` by default. To use another browser origin, set
`CORS_ORIGINS` to a JSON array of exact origins in the backend environment.
Production has no default allowed origins. Native Android requests do not need
browser CORS. See the [frontend guide](../docs/frontend-development.md) for API
URL, managed account, and physical-device networking configuration.

| Method and path | Input / behavior |
| --- | --- |
| `GET /health` | Liveness only; no model call or storage readiness guarantee |
| `POST /v1/assessments` | Multipart `assessment_id`, `photo`, optional `profiles` JSON array, `household_context`; retains upload and returns `ready` |
| `GET /v1/assessments/latest` | Latest assessment for this account; skips deletions in progress; 404 if none |
| `GET /v1/assessments?limit=20&cursor=...` | Account history, newest first; lightweight `items` and nullable `next_cursor`; skips deletions |
| `GET /v1/assessments/{aid}` | Current state, findings and linked submissions |
| `POST /v1/assessments/{aid}/analyze` | Runs initial analysis; same endpoint manually retries failures |
| `PATCH /v1/assessments/{aid}/findings/{fid}` | JSON `status`: `open`, `resolved`, or `dismissed`, optional `note` (omitted preserves the current note; empty clears it) |
| `POST /v1/assessments/{aid}/findings/{fid}/skip-follow-up` | Skips the agent's request |
| `POST /v1/assessments/{aid}/findings/{fid}/submissions` | Multipart `submission_id`, `kind` (`follow-up` or `review`), optional `text` and `photo`; returns retained `ready` submission |
| `POST /v1/assessments/{aid}/findings/{fid}/submissions/{sid}/analyze` | Runs or manually retries this linked check |
| `GET /v1/assessments/{aid}/photos/{pid}` | Private photo bytes after account ownership checks |
| `DELETE /v1/assessments/{aid}` | Removes all associated photos, then the document; repeat until 204 on partial failure |

Profiles are `Older adult`, `Child`, `Baby`, `Pet`, including multiple profiles;
`[]` selects a general assessment. Uploads accept decoded JPEG/PNG/WebP under
10 MiB and 20 megapixels. The backend applies EXIF orientation, resizes to at
most 1600 pixels per side, and stores a JPEG without metadata. IDs and photo
references are generated and checked by the server.

Initial analysis also produces a neutral room `title` (prompted at 1–4 words),
saved alongside the summary and findings. Missing/blank titles remain compatible
with older records. The frontend displays “Room assessment” with the date when
missing, and truncates titles longer than eight words without changing stored text.
History returns at most `limit` items (1–100, default 20), ordered by creation time
then ID descending. Pass the opaque `next_cursor` to load the next page; cursors
are scoped to the authenticated account. Listing/opening records never runs analysis.

For example, from the repo root in another terminal (with a running backend):

```bash
assessment_id=$(python3 -c 'import uuid; print(uuid.uuid4())')
curl --fail-with-body http://127.0.0.1:8000/v1/assessments \
  -H "Authorization: Bearer $FIREBASE_ID_TOKEN" \
  -F "assessment_id=$assessment_id" \
  -F 'profiles=["Older adult","Baby","Pet"]' \
  -F 'photo=@mobile/assets/rooms/living-room.jpg'
curl --fail-with-body -X POST \
  "http://127.0.0.1:8000/v1/assessments/$assessment_id/analyze" \
  -H "Authorization: Bearer $FIREBASE_ID_TOKEN"
```

Obtain a current verified Firebase user token through the SDK before requests. A real analysis sends the photo to the selected model provider and consumes your quota.

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

## Model adapters

The workflow depends only on `ModelProvider.generate` in
[`app/models/providers/base.py`](app/models/providers/base.py): safety
instructions, plain context, up to two private images, and a provider-neutral
output schema. The controller validates the result with Pydantic and records
provider/model provenance per analysis attempt. Routes, prompts, storage, and
user-controlled finding status remain shared.

The Muse adapter implements the supplied Meta Responses contract. It reads only
completed assistant output-text blocks, ignores reasoning items, and rejects
refusals, incomplete responses, malformed JSON, and non-object results. HTTP and
transport failures become safe diagnostic categories; raw provider bodies,
credentials, and photos are not logged. Retries remain manual.

Meta references: [Responses](https://dev.meta.ai/docs/protocols/responses),
[photo input](https://dev.meta.ai/docs/image-understanding), and
[structured output](https://dev.meta.ai/docs/structured-output).

This change covers local integration. The current Cloud Run release script and
Terraform secret setup still configure Groq; adapting cloud release tooling to
Muse is separate work. Do not treat switching the local `.env` as a cloud release.

## Verification

See [backend checks](../docs/test/backend.md) for linting, formatting, API tests,
emulator persistence checks, and the opt-in live model smoke test.

## Production configuration

Set `ENVIRONMENT=production`, the real `GOOGLE_CLOUD_PROJECT`,
`FIRESTORE_DATABASE_ID`, `PHOTOS_BUCKET`, model settings, and durable worker URL/queue/service identity.
Remove all Auth/Firestore/GCS emulator environment variables. Production rejects
emulator endpoints and requires verified managed user tokens on assessment routes. Google clients use Application Default Credentials
from the Cloud Run service account; Terraform manages storage provisioning and
private bucket configuration. The container binds `0.0.0.0:$PORT` and runs as a
non-root user. Production disables `/docs`, `/redoc` and `/openapi.json`.

Build locally with `docker build -t home-safety-backend:dev backend` from the repo
root. See [deploy/README.md](../deploy/README.md) for separate Terraform provisioning,
Secret Manager initialization, Cloud Run release verification and rollback.

## Finding highlights

Highlights start automatically when an initial assessment completes. Configure
`MODEL_PROVIDER=muse`, `MUSE_MAIN_MODEL`, backend-only `MUSE_API_KEY`, and
`MUSE_SEGMENTATION_MODEL`. The assessment call returns a short
`segmentation_prompt` per finding (internal, never returned to clients). The
completion commit saves one initial attempt per finding: `queued` with a valid
prompt, otherwise `unavailable` with a reason (no object, unusable prompt, or
unsupported configuration). Each attempt sends that prompt and the initial photo
to SAM once (`include_confidence: "true"`), parses it with `meta-sam-parser`, and
publishes the highest-confidence valid mask, falling back to provider order. There
is no main-model selection or review, so a highlight can mark the wrong instance.
Follow-up and review revisions never generate highlights.

With the existing Firestore/GCS emulators and API running, start an independent
worker from `backend/`:

```sh
.venv/bin/python -m app.annotations.local_worker
```

This worker discovers persisted work itself and runs up to 12 attempts at once.
Navigating away, stopping polling, or restarting the API does not own or cancel
it. Stopping the worker mid-attempt leaves an expired, manually retryable
failure; restarting never repeats that attempt's provider call. Attempts are
claimed independently, each with a 30-second budget excluding queue waiting time.

Finding JSON adds `content_revision`, `evidence_history`, `annotation` (current
revision), and `annotations` (attempt metadata, including `retryable`). These
routes use the normal bearer token and `X-Device-ID`:

- `POST .../findings/{finding_id}/annotations`: JSON `{ "revision": "initial", "retry": true }`.
  Explicit retry with the saved prompt: `202` with a new attempt, the active attempt
  if one is running, `200` with `supported: false` when highlighting is not
  configured, or `409` for a stale revision, a revised finding, or a legacy attempt
  without a saved prompt. Without `retry`, it returns the latest attempt.
- `GET .../annotations/{id}` returns metadata, without masks, leases or prompts.
- `GET .../annotations/{id}/mask` returns the authorized, source-sized transparent
  PNG overlay with translucent fill and outline; available only for ready,
  unreported results. The metadata binds it to the exact photo digest, upright
  orientation (`1`), width and height. Regions use top-left normalized coordinates.
- `POST .../annotations/{id}/feedback` accepts `{ "kind": "wrong_object" }` and
  persistently hides the annotation without modifying finding/checklist state.

The finding screen reads the attempt named in the assessment and polls it every
two seconds while it is queued/processing and the screen is active. It never
starts model work except through the Retry button. The overview stays unannotated.
Historical revisions keep their own content, annotation metadata and source photos.
Mask assets and metadata are deleted with their assessment. Dispatch recovery also
sweeps orphan masks; private keys and image/mask payloads never enter diagnostics.
`/internal/annotations/work` and `/internal/annotations/recover` require verified
Google OIDC tokens from the configured service identity, not a client demo token.


## Finding chat

The mobile finding screen offers **Chat about it** for every status. It no longer
submits follow-up or photo-review evidence. Legacy submission endpoints remain
compatible and completed evidence/revisions stay readable.

Authenticated endpoints, scoped to `/v1/assessments/{aid}/findings/{fid}/chat`:

| Method/path | Behavior |
| --- | --- |
| `GET` | Saved ordered turns and pending/failed state; no generation |
| `POST /turns` | JSON `{id: UUID, question: string}`; persists before generation |
| `POST /turns/{tid}/generate` | JSON `{attempt_id: UUID}`; one explicit generation/retry |

Repeat the same turn ID/question to reconcile a lost acceptance response. Different
input with that ID conflicts. Each explicit manual retry uses a fresh attempt ID;
replaying an attempt ID returns saved state without another model call. Only one
unfinished turn per finding is accepted across devices. `ready` has not started;
`running` expires after 300 seconds into an interrupted failure on read. Reopening
or polling never starts generation. An answer is saved before completion is returned.
Clients read history again after ambiguous responses, then offer manual Continue or
Retry. No provider fallback or automatic model retry occurs.

Chat is embedded as bounded per-finding operation records in the existing atomic
Firestore assessment document. It is omitted from normal assessment DTOs and exposed
only on the chat API. Transactions fence the active owner and deletion state, retain
concurrent status/highlight changes, and never recreate missing records. Assessment
and account deletion therefore cover all chat records using their existing retryable
flows. No additional collection, index, retention policy or migration is required.

Limits (enforced before acceptance and rechecked before generation):

- Question: 1–2,000 characters, excluding whitespace-only input; reply: 3,000 characters.
- 12 turns per finding; at most 10 explicit generation attempts per turn.
- 120,000 serialized chat bytes per assessment, with 40,000 bytes of acceptance
  headroom for a question, reply and metadata. No new chat is accepted once the
  assessment reaches 650,000 bytes. The existing 750,000-byte guard also reserves
  24,000 bytes for every unfinished reply, protecting concurrent writes.
- Context: at most 24,000 UTF-8 bytes for complete JSON context, safety instructions
  and output schema. Earlier chat and completed historical text are never truncated
  or summarised. Only the original room photo is resent, through private photo access.
- Model budget: `CHAT_CONTEXT_TOKENS` defaults to 65,536; set it to no more than the
  selected model's documented context window. `CHAT_IMAGE_TOKEN_RESERVE` defaults
  to 32,768 for the existing maximum 1,600px original photo; increase it if the
  provider's image token accounting requires more. The text byte budget is reduced
  further to reserve these image tokens, 6,000 output tokens and 2,048 transport
  overhead tokens. One token per UTF-8 text byte is a conservative bound, rather
  than the usual English chars/token estimate. A model/budget too small disables
  sending while preserving history. The provider/model must support the chosen
  image reserve and a 6,000-token output allocation.

Both Muse and Groq use the shared adapter boundary, strict `{answer}` output and
application-owned history. [Groq Scout's documented window](https://console.groq.com/docs/model/meta-llama/llama-4-scout-17b-16e-instruct)
is 128K. Muse capacity depends on the configured `MUSE_MAIN_MODEL`; the existing
sample does not establish a universal window, so confirm the deployment's model
allowance before increasing defaults. Recognised provider capacity errors permanently
block further sending for that conversation and show a context-limit explanation,
not a transient Retry action. Other generation failures retain the saved question.
No conversation text, photo payload or provider body is logged routinely.

Preview uses separate local conversation state and simulated replies, including a
**Chat reply retry** scenario. Account-backed chat is always refetched on reopen;
local unsent drafts and uncertain acceptance identities survive restart and are
removed with assessment deletion or account cleanup.
