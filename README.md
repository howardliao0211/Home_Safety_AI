# Home Safety AI

A mobile-first home-safety assistant that turns room photos into findings and
an actionable checklist for households with older adults, children, babies,
and pets.

The Expo / React Native frontend connects to the local FastAPI backend by
default. Submitted photos are analysed using the backend's configured model
provider (Muse for the demo; Groq remains selectable). An explicit preview mode uses predefined
examples and works without a backend or credentials.

## Development environment

### Prerequisites

- Git and a local checkout of this repository.
- Node.js **24.22.1**, pinned in [`.nvmrc`](.nvmrc), with its bundled npm.
  Install it from [Node.js](https://nodejs.org/) or use your Node version manager.
- Python **3.10+** and [uv](https://docs.astral.sh/uv/) for the backend.
- Docker Engine with Compose for the Firestore and photo-storage emulators.
  On WSL, start Docker Desktop and enable integration for your distro.
- A browser for web preview.
- Optional: an Android phone with an Expo Go version compatible with the
  project's Expo SDK **57**, available through [Expo Go](https://expo.dev/go).

Android Studio is only needed if you want to use an Android emulator. Browser
preview and a physical phone running Expo Go do not require it.

### Frontend dependencies

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

### Backend dependencies and configuration

From the repository root, confirm Docker Compose is available and install the
backend dependencies:

```bash
docker compose version
cd backend
uv sync --extra dev --locked
```

If the root `.env` does not exist, copy `.env.example` to `.env`. Configure
`MODEL_PROVIDER=muse`, `MUSE_API_KEY`, and `MUSE_MAIN_MODEL` there. To use Groq,
set `MODEL_PROVIDER=groq`, `GROQ_API_KEY`, and `GROQ_MODEL` instead. Preserve
existing credentials; model keys belong only in the backend environment.
See the [backend guide](backend/README.md#start-locally) for storage settings
and provider configuration.

### Frontend configuration

From the repository root:

```bash
cd mobile
# Only if mobile/.env does not already exist:
cp .env.example .env
```

Confirm these settings in `mobile/.env`:

```dotenv
EXPO_PUBLIC_DATA_SOURCE=api
EXPO_PUBLIC_API_URL=http://127.0.0.1:8000
EXPO_PUBLIC_DEMO_TOKEN=
```

Leave `EXPO_PUBLIC_DEMO_TOKEN` empty unless the backend has
`DEMO_BEARER_TOKEN` configured; if configured, set both to the same value.
The shared demo token is client-visible. Never put model API keys in the
frontend. Restart Expo after changing its environment.

## Test the frontend and backend locally

After completing setup above, run from the repository root on Linux or WSL:

```bash
python3 scripts/local-test.py start
```

The script starts the storage emulators, API on port 8000, highlight worker, and
frontend on port 8081 in the background. Open <http://localhost:8081> on the development machine
once it reports ready. Logs are saved under `.tools/local-test/`.
Stop any manually started API or frontend first; the script reports port
conflicts rather than replacing existing servers.

Choose **Start with a room**, select a photo or bundled sample, choose optional
household profiles, and create an assessment. This calls the selected model
provider and consumes model quota. Local API docs are at
<http://127.0.0.1:8000/docs>; liveness is at
<http://127.0.0.1:8000/healthz>. If configured, the demo bearer token is required
for API requests, including health checks.

To stop the managed frontend, worker, API, and storage emulators:

```bash
python3 scripts/local-test.py stop
```

Storage stops gracefully and preserves emulator data. See the
[local stack script guide](docs/test/local-stack.md) for logs and troubleshooting,
and [testing guides](docs/test/README.md) for automated checks, manual journeys,
preview mode, and Android device testing.

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
| `backend/` | FastAPI assessment backend, Muse/Groq adapters, Firestore/GCS storage and tests |
| `scripts/local-test.py` | Start and stop the local frontend, API, highlight worker, and storage stack |
| `docs/test/` | Automated checks, manual journeys, and device testing |
| `deploy/terraform/` | Shared Cloud Run infrastructure, storage, registry and secret IAM |
