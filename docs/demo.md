# Frontend preview checks

For the current connected API setup, see the verification entry at the end of
this document. Earlier sections record checks of the implementation at that time.

Implemented against `.scratch/frontend-preview/spec.md` on 2026-10-27.
This is a frontend demonstration with predefined results. No Muse analysis,
model accuracy evaluation, backend, or cloud persistence was exercised.

## Run the review

```bash
source scripts/frontend-env.sh
cd mobile
npm run web
```

Open the printed localhost URL. On first use, choose **Start with a room**.
Use a camera/gallery photo or a bundled sample, select optional profiles
(including **Baby**), confirm, and create a sample assessment.

**Preview** in the development header selects a scenario for the next fresh
demo. It does not change existing assessments. Start a fresh demo to inspect
uncertainty, no obvious hazards, analysis retry, linked-update retry, or camera
permission denial. A current draft requires confirmation before replacement.

For Android, run `npm start` and scan the QR code with SDK-compatible Expo Go.
Use `npm run start:tunnel` if WSL/LAN networking prevents phone access.

## Automated verification performed

- TypeScript checking passed.
- Seven state/service tests passed: serialized durable writes, rollback after
  storage failure, interrupted-operation recovery, preservation of user status,
  linked-update identity, photo retention, counts, and explicit analysis retry.
- Fourteen Chromium browser journeys passed, covering:
  - Multiple profiles, resolve/dismiss/reopen, notes, and restart persistence.
  - Text clarification and photo review without automatic resolution.
  - Skipping an agent follow-up while retaining user-requested review.
  - Failed analysis and linked updates, retained input, and manual retry.
  - Actual browser file upload persisted as image data across reload.
  - Draft cancellation, confirmation, assessment deletion, and restoration of
    the latest remaining assessment.
  - Qualified no-hazards and all-items-handled states.
  - Simulated camera denial with alternate input.
  - Injected IndexedDB quota failure without falsely saved status changes.
  - Reload during processing followed by explicit interrupted-state retry.
  - Preserving an edited text answer before back navigation.
  - Confirmed reset of assessments and unfinished draft data.
  - Layouts at 320px, 430px, and 1280px with no document horizontal overflow.
- Expo dependency compatibility passed; Expo Doctor passed all 21 checks after
  aligning the native font and animation dependencies to SDK 57.
- Web and Android exports passed. A normal browser journey produced no browser
  console errors or warnings in a separate runtime check.

Screenshots were inspected at phone widths. The first action is visible without
scrolling through the introduction; results show the next actions, readable
severity labels, and explicit preview status. Screenshots and test failure
artifacts are saved in ignored `.tools/screenshots/` and `.tools/browser-results/`.

## Physical-device and manual checks still needed

This environment has no attached Android device, adb, or configured emulator.
An Android bundle is not proof that device behavior works. Complete these in
Expo Go before accepting the physical-device demo:

- Real camera and gallery capture; cancellation; actual permission denial and
  device-settings recovery; camera activity interruption.
- Restart with initial, follow-up, and review photos, then confirmed deletion
  and verification that associated app-owned photo files are removed.
- Android system back, gesture navigation, landscape, keyboard overlap, and
  safe areas with both gesture and three-button navigation.
- Largest system font/display sizes, TalkBack focus and state announcements,
  reduced-motion preference, and dark system appearance with the light app theme.
- Browser keyboard focus through dialogs and file selection on target browsers.
  Browser camera availability depends on device/browser support; file upload
  and bundled samples are the supported fallback.

## Limitations

- Fixture descriptions do not establish hazards in the selected or bundled room
  photos. Preview disclosure is intentional and must stay visible.
- Data is local to this browser origin or app installation. Clearing browser/app
  data removes it. Local records do not implement the eventual VM persistence
  or device-scoped API contract.
- Earlier assessments are retained but have no history browser. Deleting the
  latest one restores the latest remaining record.
- Browser image selections use IndexedDB; native image copies use the app's
  document directory. Storage failures remain visible and do not publish a
  falsely saved action. Failed photo cleanup offers an explicit retry.
- Large browser uploads are limited to 15 MB for this preview.
- Eight npm dependency advisories remain (three high, five moderate), involving
  Expo CLI/Zod, Router URL parsing, and tunnel support. No forced major SDK
  downgrade or unverified dependency override was applied.
- iOS, dark theme, live backend/Muse integration, history, and annotations are
  outside this implementation.

## Reproduce automated checks

From `mobile/`:

```bash
npm run typecheck
npm test
npx playwright install chromium
npm run test:e2e
npx expo install --check
npx expo-doctor
npx expo export --platform web --platform android
```

The browser runner starts or reuses a localhost Expo server on port 8081.
Use `npm run format` to format frontend source and tests.

## Backend verification — 2026-10-27

The FastAPI backend now implements the assessment, linked follow-up/review,
finding-status, retained-photo, latest-assessment, and deletion workflows.
Groq is the explicitly selected development provider; Muse awaits its actual
API contract. Setup and the HTTP contract are in [backend/README.md](../backend/README.md).

Verified:

- 36 automated checks passed with workflow, provider-boundary, Firestore/GCS,
  and container-restart checks enabled. The paid live-model test was excluded
  from that passing run. Ruff lint and format checks passed.
- Workflow checks cover failure retention, explicit retry, idempotent uploads
  and analysis, per-device scoping, partial deletion retry, skipped follow-ups,
  independent photo reviews, and preservation of user status and notes.
- Actual Firestore/GCS SDK round trips passed, including fresh storage clients,
  linked revisions, private photo retrieval, status persistence and deletion.
- Both emulator containers were stopped and restarted. Assessment state and
  photos survived. The Firestore launcher explicitly exports before stopping
  Java and restores the last successful snapshot; the pinned emulator's native
  shutdown export was unreliable in testing.
- A running Uvicorn process passed HTTP checks for health, OpenAPI, upload,
  latest assessment, photo retrieval and deletion using the existing `.env`.

Groq is selected through `MODEL_PROVIDER=groq`, with backend-only
`GROQ_API_KEY` and `GROQ_MODEL=qwen/qwen3.8-27b`. With the corrected credentials,
a real room-photo assessment and a linked two-image photo review both returned
HTTP 200 with validated structured output.

Groq initially returned HTTP 429 for the linked review. Its input and the
assessment findings were retained. An explicit manual retry of that same
submission later returned HTTP 200 with feedback, without changing the user's
finding status. The live test's two calls can still exceed a small development
quota even with a one-minute gap. `LIVE_MODEL_INTERVAL_SECONDS` only paces the
opt-in smoke test; the application has no automatic model retries.

The restored Groq provider passed 38 workflow/provider/storage tests, including
the Groq URL and authorization header, strict JSON request shape, safe failure
handling, retained inputs, and user-controlled finding status. The two-call live
pytest run hit quota limits; the successful live assessment/review/manual-retry
sequence was verified separately against the real API and local storage.

The mobile app continues to use its simulated service. Phone-to-backend
integration, cloud deployment, Muse integration and physical-device checks
remain separate work. These tests establish integration/state behavior, not
hazard-detection accuracy.

## Cloud Run Docker workflow verification — 2026-10-28

Cloud Run replaces the earlier VM hosting plan. The deployment guide is
[deploy/README.md](../deploy/README.md); shared resources are provisioned with
Terraform and `scripts/deploy-gcp.py` owns releases, traffic and rollback.

Verified locally:

- Built the production Linux AMD64 image from locked dependencies and pinned
  Python/uv images. The runtime image is approximately 78 MB and runs as UID 10001.
- Ran the image against local Firestore/GCS services using a custom `PORT` and
  dummy model credentials. Authenticated health, photo/assessment CRUD, device
  scoping, deletion and the internal Docker health check passed; no model call.
- Ran the production image with synthetic test-only credentials, without cloud
  operations. Missing/wrong bearer tokens were rejected, authenticated health
  succeeded, and production documentation routes returned 404.
- 45 backend/deployment/storage checks passed. The live model test was excluded
  and the optional emulator-container restart check was skipped in this run.
  Checks include secret stdin handling, candidate failure without promotion,
  previous-traffic restoration after a failed promotion check, and using a
  rollback revision's original secret version.
- Ruff lint/format, Terraform formatting/validation and diff checks passed.

No GCP provisioning, image push, Secret Manager update or Cloud Run deployment
was performed. Actual cloud IAM, candidate URLs, public invocation and revision
traffic changes still require a provisioned service and live release check.

## Local frontend/API continuation — 2026-10-28

The frontend now defaults to the FastAPI client; fixture-only previews require
`EXPO_PUBLIC_DATA_SOURCE=preview`. Setup instructions, device networking, bearer
token configuration, and test ports are documented in the root README and
[frontend guide](frontend-development.md). Model credentials stay backend-only.

Verified in this checkout:

- TypeScript checking and all 12 frontend unit tests passed.
- All 14 preview Chromium journeys passed.
- 45 backend tests passed; three opt-in emulator/restart/live tests were skipped.
  Ruff lint and formatting checks passed.
- Chromium libraries are available; no project-local browser library workaround
  is required in this environment.

The connected browser suite was attempted but its API fixture could not start:
the GCS emulator at `127.0.0.1:4443` refused connections. Docker Desktop's WSL
integration is unavailable, neither storage emulator is running, and this
checkout has no root `.env`. Connected browser journeys and the actual
browser → FastAPI → Groq path remain unverified in this continuation. No live
model request or cloud deployment was performed. Restore backend credentials
locally without sharing them, enable Docker's WSL integration, start the storage
emulators, and run `npm run test:e2e:api` before the separate live-model check.

Review identified and corrected a restoration edge: a retained server assessment
with `status=ready` now requires explicit Retry after reconnecting. Reloading a
failed upload must not automatically retry that upload or start model analysis.
Physical Android networking and camera checks remain pending.

## Muse local integration — 2026-10-28

The supplied Meta Responses sample is now implemented by a dedicated Muse
adapter. Local configuration selects `MODEL_PROVIDER=muse` using backend-only
`MUSE_API_KEY` and `MUSE_MAIN_MODEL`. Groq remains explicitly selectable, without
fallback. Requests use inline photos, strict structured output, and `store=false`
to disable Meta-managed response history. App retries remain manual.

Verified against the configured live Muse model:

- The bundled room photo produced a Pydantic-valid assessment; a separate
  two-image review produced a valid revised finding and feedback.
- Chromium → Expo → FastAPI → Muse → Firestore/GCS completed an assessment,
  restored it after reload, and completed a linked evidence check. A finding
  marked resolved by the user stayed resolved after the model update.
- The browser check used a new device identity and removed its assessment and
  photos afterward. No existing user assessments were changed.

The backend suite passed 60 tests with three opt-in tests skipped; an additional
Firestore/GCS round-trip check passed against the running storage emulators.
Ruff lint and format checks passed. These establish integration behavior, not
hazard-detection accuracy. The local browser check used the concurrent frontend
fetch-receiver fix present in the workspace.

Frontend typechecking and all 13 unit tests passed. All three deterministic
connected Chromium journeys passed against emulator storage, including retained
initial and linked failures, manual retries, frozen submitted evidence, private
photo restore, status persistence, and deletion. The immutability assertion now
checks that the readonly answer cannot be edited rather than requiring a
disabled textarea.

No cloud release or infrastructure changes were made. Cloud release tooling
still configures Groq and needs separate Muse configuration before deployment.
