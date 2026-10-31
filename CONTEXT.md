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
- Ask text questions in a saved, finding-scoped conversation without changing
  the finding, its evidence revisions, highlights, or checklist status.
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

**Suggestions**: Exactly three short, plain-text priorities saved with a new
assessment's initial analysis when it has findings (none when it has no findings),
using household profiles and details where relevant. They are never regenerated.
Older records keep their original prose summary instead.

**Household details**: Optional free text (up to 3,000 characters) describing the
household, such as ages, mobility needs or pets. Trimmed and frozen into one
assessment at creation; supplied to the model as context separate from household
profiles, never as instructions. Stored as `household_context` /
`householdContext`.

**Room concept**: A private, saved AI-generated illustration of changes to the
original room photo based on the initial findings and household context. New
assessments with findings queue one automatically when `MUSE_IMAGE_GEN_MODEL` and
Muse credentials are configured. Only explicit retry after failure can make another
attempt; success is never regenerated. Opening the viewer only reads saved state.
Concepts are not evidence, do not change finding status and never certify safety.
They are deleted with their assessment/account.

**Finding chat**: A saved, text-only advisory conversation belonging to one finding.
Each answer uses the original room photo, household context, current finding, earlier
chat and completed historical discussion. Chat never changes findings or status.
Only the authenticated backend reads/writes conversations in Firestore. Unsent drafts
remain local and account-scoped. Each reply is a durable **chat job** (queued, running,
complete or failed) that runs in the backend worker independently of the app and
streams its answer into one growing assistant message. A failed attempt keeps its
partial text as an **Incomplete response**; an explicit Retry replaces it with a fresh
answer to the same question. Incomplete text never enters later model context. New follow-up/photo-review submissions are no longer
offered in the frontend; saved historical evidence remains viewable.

**Follow-up**: Historical focused clarification or targeted photo evidence linked to
one finding. Legacy backend endpoints remain compatible, but new frontend guidance
uses finding chat rather than follow-up or photo-review controls.

**Checklist**: The prioritised actions recommended for an assessment, with exactly
one completable checklist item per finding in the MVP.

**Finding status**: `open`, `resolved`, or `dismissed`. The user is the final
reviewer and decides when an item is resolved. Chat provides guidance but never automatically resolves an item. Dismissal
means the finding is not relevant, with an optional user note. The user can
reopen a resolved or dismissed finding.

## Assessment behavior

- Assess: report potential hazards only where there is visible support.
- Discuss: offer Chat about it on every finding, including resolved and dismissed
  findings. Opening chat only loads history. The user sends text questions and can
  manually retry failed replies. State remaining uncertainty explicitly.
- Plan: recommend concise, prioritised, low-risk actions and professional help
  where appropriate.
- Update: revisit the relevant finding when new evidence or a user action arrives.
  Absence from a later photo does not establish that a hazard is resolved.
- Historical evidence: retain earlier completed follow-ups, photo reviews, content
  revisions and highlights for viewing. Chat does not submit new photos or revise
  this evidence. Only the user controls finding status.
- A result with no obvious visible hazards is not a declaration that the room is safe.

The assistant must avoid instructions for dangerous work, such as repairing
electrical wiring or moving heavy furniture alone. Urgent danger calls for
leaving the area and seeking appropriate emergency or professional help.
External actions require user approval; booking and shopping are outside the MVP.

Display: “AI-generated suggestions based on visible information only; not a
professional home safety inspection.”

## Technical direction

- Mobile: Expo / React Native, with Android first for the physical-device demo.
  Account flows target Android and iOS; native device verification remains required.
- Backend: FastAPI, including the assessment controller, in a Docker container
  on GCP Cloud Run in Sydney (`australia-southeast1`), project `home-safety-ai`. Start with 1 CPU,
  2 GiB RAM, concurrency 8, minimum 0 and maximum 2 instances, and a 300-second
  request timeout. Container images live in Artifact Registry.
- Model integration: Meta Muse is the demo provider, selected explicitly with
  `MODEL_PROVIDER=muse`, backend-only `MUSE_API_KEY`, and `MUSE_MAIN_MODEL`.
  The supplied Meta sample establishes `https://api.meta.ai/v1/responses` and
  bearer authentication. The Muse adapter sends inline photos and requests strict
  structured output with server-managed response history disabled. Groq remains
  available for development through `MODEL_PROVIDER=groq`, `GROQ_API_KEY`, and
  `GROQ_MODEL`. Both implement the shared model adapter interface. There is no
  automatic provider fallback or model retry.
- Persistence: Firestore Standard edition in Native mode, located in `australia-southeast1`.
  Regional resources move only through a destructive rebuild (`deploy rebuild`),
  which discards assessment data and keeps accounts and model secrets.
  FastAPI accesses Firestore using the dedicated Cloud Run service account; the mobile
  app accesses all assessment data through FastAPI. No SQLite or separate data disk.
  Local development uses the Firestore emulator and a GCS-compatible local service;
  preserve emulator data across graceful restarts. Cloud provisioning is deferred.
- Account scope: managed Identity Platform/Firebase email/password accounts with
  verified email. Firebase UID owns assessments, photos, submissions and highlights.
  The same account reopens its latest assessment across Android/iOS installations;
  Home lists retained assessments through account-scoped paginated history;
  live synchronization remains excluded. Account namespaces
  are separate from legacy device data, which is never automatically imported.
  See `docs/authentication.md` for authentication, persistence and deletion.
- Photo retention: retain initial, follow-up, and user-review photos with their
  assessment. User deletion removes the assessment and its associated photos.
  Store photos in a private regional GCS bucket accessed by the backend only.
  Disable object versioning and soft delete so app deletion does not deliberately
  retain recoverable photo versions. Database and photo deletion are separate
  operations: the backend must make deletion retryable across both stores.
- Credentials: model API keys remain on the backend and secrets stay out of Git.
- Transport authentication: public Cloud Run HTTPS invocation permits mobile
  access; FastAPI verifies current Firebase user ID tokens with revocation checks.
  `/health` is public liveness; internal workers use allowlisted service OIDC.
  API docs are disabled in production. Model keys use numbered Secret Manager
  versions and never enter images or clients. Account deletion uses a durable
  tombstone, independent recovery sweep, and a limited status receipt.
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
if chat or legacy evidence analysis fails. Persist accepted chat questions and their
queued reply job together; recovery fails interrupted or unstarted jobs after bounded
deadlines and requires an explicit manual retry, never restarting a model stream. Context/storage limits retain readable history and drafts. Automatic retries are outside the current MVP
scope. A failed analysis must not be presented as a successful assessment or
a no-hazards result.

## Scope boundaries

- Required: photo input, structured findings, saved finding chat, checklist state,
  restart persistence, and phone-to-cloud connectivity.
- Stretch goals, only if time remains after the required one-week scope:
  assessment comparisons. Illustrative room concepts are now approved scope;
  see `.scratch/room-concept/spec.md`.
  Annotations require reliable localisation and validated normalised coordinates;
  redesign must never be presented as a validated safety improvement.
- Persist assessment and draft state across restarts. Home is the default entry
  point, with previous assessments listed newest first and one local draft available
  to resume. See `.scratch/home-history/spec.md` for the launch, Home and history flow.
- Starting a new assessment retains earlier assessments and their photos.
  Users can reopen earlier assessments from Home with all existing checklist actions.
  An assessment title is generated with the initial analysis and retained on the
  backend; missing titles display as “Room assessment” with the creation date.
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
- The mobile app connects to FastAPI by default; explicit preview mode uses
  simulated assessments and separate local state. The FastAPI backend implements
  assessment workflows with Muse/Groq adapters and Firestore/GCS storage. Local setup and
  the HTTP contract are documented in `backend/README.md`.
  Shared GCP resources live in `deploy/terraform/`; `scripts/deploy-gcp.py` owns
  image releases, Cloud Run revisions/traffic, verification and rollback.
  Provisioning and releases are separate; see `deploy/README.md`.

**Finding-content revision**: A saved version of a finding's explanation and
supporting evidence, separate from its checklist status. Successful follow-up or
review analysis creates a new revision; status changes and failed analysis do not.

**Highlight** (annotation): An optional, AI-generated, unreviewed localisation of
one main visible object in the initial assessment photo for an initial finding.
The assessment names the object with a short segmentation prompt; SAM supplies
the mask. It helps locate evidence, may mark the wrong instance, and does not
verify safety, anchoring, or resolution.
Highlights are tinted by the finding's severity when served (High red, Medium
yellow, Low green; historical highlights use their revision's severity), including
masks stored before colours existed. The checklist photo overlays the latest ready,
current-revision, original-photo highlight of each open finding; translucent
overlaps blend and carry no extra meaning. Missing highlights never mean "safe".

**Highlight attempt**: One prompt-based segmentation of a saved prompt and photo,
with a persisted outcome. Initial attempts start when the assessment completes and
run independently of each other and of the app. Retrying is an explicit user
action that reuses the saved prompt; reporting an incorrect object hides that
result without changing the finding's status. Follow-up and review revisions do
not generate highlights.
