# Home Safety AI

A mobile-first home-safety assistant that turns room photos into findings and
an actionable checklist for households with older adults, children, babies,
and pets.

The Expo / React Native frontend connects to the local FastAPI backend by
default. Submitted photos are analysed using the backend's configured model
provider (Groq for development). An explicit preview mode uses predefined
examples and works without a backend or credentials.

## Development environment

### Prerequisites

- Git and a local checkout of this repository.
- Node.js **24.22.1**, pinned in [`.nvmrc`](.nvmrc), with its bundled npm.
  Install it from [Node.js](https://nodejs.org/) or use your Node version manager.
- A browser for web preview.
- Optional: an Android phone with an Expo Go version compatible with the
  project's Expo SDK **57**, available through [Expo Go](https://expo.dev/go).

Android Studio is only needed if you want to use an Android emulator. Browser
preview and a physical phone running Expo Go do not require it.

### Install dependencies

Open a terminal at the repository root. If you use nvm, select the pinned Node
version first:

```bash
nvm install
nvm use
```

Then install the frontend dependencies from the lockfile:

```bash
cd mobile
node --version
npm --version
npm ci
```

`npm ci` must run inside `mobile/`; there is no root npm project.

### Existing project-local Node installation

This development checkout may already contain a Linux Node runtime in the
ignored `.tools/` directory. To use it from Bash, run from the repository root:

```bash
source scripts/frontend-env.sh
cd mobile
npm ci
```

Source the script in each new terminal. It selects the project-local runtime
when present and otherwise uses Node already on your `PATH`. It does **not**
install Node; `.tools/` is not included in a fresh clone.

For WSL development, use Linux Node and npm inside WSL. If npm reports a WSL or
Node installation-directory error, check `command -v node` and `command -v npm`:
they should point to Linux executables, rather than Windows paths under `/mnt/c/`.

## Test the frontend and backend locally

Use two terminals, starting each in the repository root. You need Python 3.10+,
[uv](https://docs.astral.sh/uv/), Docker Engine with Compose, and the frontend
dependencies installed above. On WSL, start Docker Desktop and enable its WSL
integration for your distro. Confirm `docker compose version` works in WSL.

### Terminal 1: storage and backend

If the root `.env` does not exist, copy `.env.example` to `.env`. Edit it locally
to set `MODEL_PROVIDER=groq`, `GROQ_API_KEY`, and `GROQ_MODEL`. Preserve any
existing credentials; model keys belong only in the backend environment.

```bash
docker compose -f backend/compose.yaml up -d
cd backend
uv sync --extra dev --locked
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

Keep this terminal running. Local API docs are at
<http://127.0.0.1:8000/docs>; liveness is at
<http://127.0.0.1:8000/healthz>. If you configured `DEMO_BEARER_TOKEN`, API
requests, including health checks, require its bearer header. See the
[backend guide](backend/README.md#start-locally) for storage settings and logs.

### Terminal 2: frontend

```bash
source scripts/frontend-env.sh
cd mobile
# Only if mobile/.env does not already exist:
cp .env.example .env
```

Confirm these settings in `mobile/.env`:

```dotenv
EXPO_PUBLIC_DATA_SOURCE=api
EXPO_PUBLIC_API_URL=http://127.0.0.1:8000
```

If the backend has
`DEMO_BEARER_TOKEN` configured, set the matching `EXPO_PUBLIC_DEMO_TOKEN` in
`mobile/.env`. This shared demo token is client-visible; never put model API
keys in the frontend. Restart Expo after changing its environment.

```bash
npm run web
```

Open the localhost URL printed by Expo, usually `http://localhost:8081`.
Use port 8081 for the documented local CORS defaults.

Choose **Start with a room**, select a photo or bundled sample, choose optional
household profiles, and create an assessment. This sends a real request to Groq
and consumes model quota. Check that findings appear, resolve/dismiss actions
survive reload, a linked follow-up updates its finding, and confirmed deletion
removes the assessment. Failed analysis retains the input and offers an explicit
Retry action.

If the app shows **Retry connecting**, check that both emulator containers and
Uvicorn are running, the API URL is correct, and the demo tokens match. A Groq
quota error requires a manual retry after cooldown.

### Automated connected test without model calls

With the storage emulators running and backend/frontend dependencies installed,
run from `mobile/`:

```bash
npx playwright install chromium
npm run test:e2e:api
```

This starts its own test API on 8001 and frontend on 8082 with a deterministic
model. Keep those ports free. It checks integration behavior without calling
Groq; it does not verify live model output.

### Stop local testing

Stop the frontend and Uvicorn with **Ctrl+C** in their terminals. From the
repository root, stop storage gracefully so local data is preserved:

```bash
docker compose -f backend/compose.yaml stop
```

## Run the frontend separately

Run the following commands from `mobile/`.

### Browser preview without the backend

For fixture-only demos without the API, run:

```bash
EXPO_PUBLIC_DATA_SOURCE=preview npm run web
```

In preview mode only, **Preview** in the development header selects scenarios
or resets local preview data. The selected photo is not analysed in this mode.

### Android phone

```bash
npm start
```

Set `EXPO_PUBLIC_API_URL` to the development machine's reachable LAN address
with port 8000 and bind Uvicorn to `0.0.0.0`. For an Android emulator, use
`http://10.0.2.2:8000`. A phone's `localhost` refers to the phone itself.
Connect the phone and development machine to the same network, then scan the
terminal's QR code with Expo Go. If WSL networking or a firewall prevents the
phone from reaching the LAN address, use the installed tunnel support:

```bash
npm run start:tunnel
```

Tunneling requires internet access and exposes the development server through
a temporary public URL. It tunnels Expo only; the phone still needs a reachable
API URL. Stop the server when finished.

For an emulator, first configure Android Studio, the Android SDK, and `adb`,
start an emulator, then run `npm run android`.

## Development checks

From `mobile/`:

```bash
npm run typecheck
npm test
```

Install the test browser once, then run the browser journeys:

```bash
npx playwright install chromium
npm run test:e2e
# Requires backend dependencies and running storage emulators; no model calls:
npm run test:e2e:api
```

The preview browser runner starts its own Expo server on port 8083. The API
suite starts a deterministic model fixture on 8001 and Expo on 8082, using real
storage emulators on 8080 and 4443. Screenshots and test artifacts are written
to the ignored `.tools/` directory. Neither suite calls Groq.

Check Expo compatibility and build both targets without an Android SDK:

```bash
npx expo install --check
npx expo-doctor
npx expo export --platform web --platform android
```

Use `npm run format` to format the frontend source and tests.

## Project layout

| Path | Purpose |
| --- | --- |
| `mobile/app/` | Expo Router pages and navigation |
| `mobile/src/components/` | Shared UI and design tokens |
| `mobile/src/domain/` | Assessment, finding, and checklist state |
| `mobile/src/api/` | FastAPI client, photo uploads, and explicit preview service |
| `mobile/src/hooks/` | Shared frontend state and actions |
| `mobile/src/storage/` | Local persistence and photo retention |
| `mobile/tests/` | State tests and browser journeys |
| `backend/` | FastAPI assessment backend, Groq adapter, Firestore/GCS storage and tests |
| `deploy/terraform/` | Shared Cloud Run infrastructure, storage, registry and secret IAM |

API mode retains assessment state and photos through the backend, scoped by a
persistent device ID. Preview data stays on the device. Each mode uses separate
local state; reloads retain assessments and checklist actions. Confirmed deletion
removes the selected assessment and its associated photos.

See the [frontend development guide](docs/frontend-development.md) for more
detail, [demo notes](docs/demo.md) for verified behavior and pending device
checks, and [CONTEXT.md](CONTEXT.md) for product requirements and the planned
backend architecture.

See the [backend development guide](backend/README.md) to run the real Groq-backed
API locally, inspect its endpoints, and prepare the future Muse integration.
The frontend uses this API by default; preview mode remains available explicitly.

See the [Cloud Run deployment guide](deploy/README.md) for the production Docker
image, separate Terraform provisioning, Secret Manager setup, verified releases
and rollback. The deployment script is `scripts/deploy-gcp.py`.
