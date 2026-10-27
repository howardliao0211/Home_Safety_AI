# Home Safety AI

Home Safety AI is a mobile-first assistant that uses room photos to identify
potential visible hazards, request clarifying evidence, and produce an actionable
checklist. It provides guidance, not a professional inspection or safety certification.

## MVP goal

Deliver a working phone-to-cloud demonstration within one week:

- Capture or select a room photo and optionally provide household context.
- Return potential hazards with visible evidence, severity, recommendations,
  and explicit uncertainty.
- Show findings as readable cards.
- Request a targeted follow-up photo for a specific unresolved finding and use
  it to revise that finding.
- Let the user resolve or dismiss findings and retain assessment/checklist state
  across app restarts.
- Demonstrate a visible hazard, an uncertain case, and a room with no obvious
  visible hazards.

The first demo supports all three audience groups: households with older adults,
young children (including infants), and pets. None of these groups is deferred.
Users can select multiple household profiles for one assessment. Selecting none
produces a general assessment.

## Language

**Assessment**: A review of an initial room photo and its associated findings,
follow-up evidence, and checklist state. Follow-up photos belong to the existing
assessment rather than starting an unrelated review.

**Finding**: A potential hazard supported by visible evidence. A finding includes
a category, severity, evidence, recommendation, uncertainty, and status;
`hazard_id` in the proposed API identifies a finding.

**Household profile**: Optional context identifying household members whose
needs may affect the assessment, such as an older adult, child, infant, or pet.

**Follow-up**: A focused question or targeted photo request linked to a specific
finding, intended to clarify an uncertainty. Clarification questions can be
answered with text; visual checks require a photo.

**Checklist**: The prioritised actions recommended for an assessment, with exactly
one completable checklist item per finding in the MVP.

**Finding status**: `open`, `resolved`, or `dismissed`. The user is the final
reviewer and decides when an item is resolved. The user may ask the agent to
check an item, but the agent's review never automatically resolves it. Dismissal
means the finding is not relevant, with an optional user note. The user can
reopen a resolved or dismissed finding.

## Assessment behavior

- Assess: report potential hazards only where there is visible support.
- Investigate: ask a focused question or request a targeted close-up when an
  important concern cannot be determined from the current image. Allow at most
  one agent-initiated follow-up request per finding and let the user skip it.
  If uncertainty remains, state it explicitly and let the user continue.
- Plan: recommend concise, prioritised, low-risk actions and professional help
  where appropriate.
- Update: revisit the relevant finding when new evidence or a user action arrives.
  Absence from a later photo does not establish that a hazard is resolved.
- Review: the user can request an agent check of an item before deciding whether
  to mark it resolved by submitting a new photo linked to the finding.
  User-requested reviews remain available after the single agent-initiated
  follow-up request; the user always makes the final resolution decision.
- A result with no obvious visible hazards is not a declaration that the room is safe.

The assistant must avoid instructions for dangerous work, such as repairing
electrical wiring or moving heavy furniture alone. Urgent danger calls for
leaving the area and seeking appropriate emergency or professional help.
External actions require user approval; booking and shopping are outside the MVP.

Display: “AI-generated suggestions based on visible information only; not a
professional home safety inspection.”

## Technical direction

- Mobile: Expo / React Native, with Android first for the physical-device demo.
  iOS support is deferred.
- Backend: FastAPI, including the assessment controller, in a Docker container
  on GCP Cloud Run in `us-central1`, project `home-safety-ai`. Start with 1 CPU,
  2 GiB RAM, concurrency 2, minimum 0 and maximum 2 instances, and a 300-second
  request timeout. Container images live in Artifact Registry.
- Model integration: Meta Muse remains required for the final hackathon demo.
  Groq is explicitly permitted for development while Muse access is pending.
  Select the provider using `MODEL_PROVIDER`; Groq uses backend-only
  `GROQ_API_KEY` and `GROQ_MODEL`. There is no automatic provider fallback.
  The hackathon organisers will provide the Muse API. Defer exact model ID,
  endpoint, credentials, and API contract until their integration details arrive;
  do not assume the public Meta Model API or `muse-spark-1.3` is the supplied API.
  Isolate each API behind the shared model adapter interface. Implement the Muse
  adapter when its supplied contract arrives, then select it through configuration.
  Public API research does not determine this integration.
- Persistence: Firestore Standard edition in Native mode, located in `us-central1`.
  FastAPI accesses Firestore using the dedicated Cloud Run service account; the mobile
  app accesses all assessment data through FastAPI. No SQLite or separate data disk.
  Local development uses the Firestore emulator and a GCS-compatible local service;
  preserve emulator data across graceful restarts. Cloud provisioning is deferred.
- Device scope: each app installation has a persistent `device_id`, without
  accounts or cross-device synchronisation. Scope assessment reads, uploads,
  updates, photo retrieval, and deletion by that identifier so the app shows
  only that device's records. This is MVP record scoping, not authenticated identity.
- Photo retention: retain initial, follow-up, and user-review photos with their
  assessment. User deletion removes the assessment and its associated photos.
  Store photos in a private regional GCS bucket accessed by the backend only.
  Disable object versioning and soft delete so app deletion does not deliberately
  retain recoverable photo versions. Database and photo deletion are separate
  operations: the backend must make deletion retryable across both stores.
- Credentials: model API keys remain on the backend and secrets stay out of Git.
- Demo transport: Cloud Run's managed HTTPS `run.app` endpoint. Public Cloud Run
  invocation permits mobile access; FastAPI enforces a shared demo bearer token
  and per-device assessment scoping. Production API docs are disabled. Google
  sign-in, individual accounts and broader abuse controls remain outside the MVP.
  API keys and the demo token use numbered Secret Manager versions; secret values
  stay out of images and Terraform state. The image contains no local `.env`.
- Infrastructure: Terraform configuration and provider lockfile are versioned in
  Git; Terraform state remains local and ignored, with private backups required.
  Deletion guards are removed by explicit user request: Firestore deletion protection
  is disabled and Terraform may delete the photos bucket, including its objects.

The handoff's endpoint shapes and example JSON are proposals, not implemented
contracts. The core operations are creating an assessment, submitting a linked
follow-up, updating finding status, retrieving an assessment, and checking health.
Validate model output on the server before returning or persisting it.

## Failure diagnosis

Log analysis failures so developers can investigate and fix their root causes.
Include the failed operation, assessment/finding identifiers when available,
a request correlation identifier, error category, and diagnostic exception details.
Keep API credentials and image payloads out of logs.
On analysis failure, show the error and a Retry button in the app. Retain the
submitted photo or text so a manual retry repeats the failed operation within
the same assessment without duplicating findings. Preserve existing findings
if a follow-up or review fails. Automatic retries are outside the current MVP
scope. A failed analysis must not be presented as a successful assessment or
a no-hazards result.

## Scope boundaries

- Required: photo input, structured findings, linked follow-up, checklist state,
  restart persistence, and phone-to-cloud connectivity.
- Stretch goals, only if time remains after the required one-week scope:
  photo annotations, basic scan history/comparison, and illustrative image redesign.
  Annotations require reliable localisation and validated normalised coordinates;
  redesign must never be presented as a validated safety improvement.
- Persist the current assessment across restarts without requiring a history screen.
- Starting a new assessment retains earlier assessments and their photos.
  The MVP reopens the latest assessment; browsing earlier assessments remains
  a stretch goal with the history screen.
- Excluded: 3D/floor-plan mapping, shopping, contractor booking, and live surveillance.
- No separate `evals/` directory or evaluation framework for this MVP. Record
  manual demo checks and observed failure cases in `docs/demo.md` when needed.
  Describe qualitative limitations rather than claiming detection accuracy from
  a small demo set.

## Repository conventions

- `mobile/`: screens, components, API access, hooks, local storage, and assets.
- `backend/`: routes, assessments and prompts, model adapters, storage, migrations,
  and tests.
- `deploy/` and `scripts/`: deployment configuration and development utilities.
- `docs/agents/`: engineering skill configuration; `docs/adr/`: settled decisions
  that warrant an architecture decision record.
- `.scratch/<feature>/`: local specs and individual implementation tickets.
- The mobile preview uses simulated assessments and local state. The FastAPI
  backend implements assessment workflows with a Groq development adapter and
  Firestore/GCS storage; mobile API integration is separate work. Local setup and
  the HTTP contract are documented in `backend/README.md`.
  Shared GCP resources live in `deploy/terraform/`; `scripts/deploy-gcp.py` owns
  image releases, Cloud Run revisions/traffic, verification and rollback.
  Provisioning and releases are separate; see `deploy/README.md`.

## Pending integration details

- Obtain the Muse API integration details from the hackathon organisers when available.

