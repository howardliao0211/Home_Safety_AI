# Home Safety AI

A mobile-first home-safety assistant that turns room photos into findings and
an actionable checklist for households with older adults, children, babies,
and pets.

The current frontend is an interactive Expo / React Native preview. Results
are predefined examples; the selected photo is **not analysed**. You can develop
and review the complete flow without a backend, Muse credentials, or an `.env`
file.

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

## Run the frontend

Run these commands from `mobile/`.

### Browser

```bash
npm run web
```

Open the localhost URL printed by Expo, usually `http://localhost:8081`.
Saved code changes refresh the preview. Stop the server with **Ctrl+C**.

Choose **Start with a room**, select a photo or bundled sample, choose optional
household profiles, and create a sample assessment. Use **Preview** in the
development header to select scenarios for fresh demos or reset local data.

### Android phone

```bash
npm start
```

Connect the phone and development machine to the same network, then scan the
terminal's QR code with Expo Go. If WSL networking or a firewall prevents the
phone from reaching the LAN address, use the installed tunnel support:

```bash
npm run start:tunnel
```

Tunneling requires internet access and exposes the development server through
a temporary public URL. Stop the server when finished.

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
```

The browser runner starts or reuses an Expo server on port 8081. Screenshots
and test artifacts are written to the ignored `.tools/` directory.

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
| `mobile/src/api/` | Simulated service, ready for later backend integration |
| `mobile/src/hooks/` | Shared frontend state and actions |
| `mobile/src/storage/` | Local persistence and photo retention |
| `mobile/tests/` | State tests and browser journeys |
| `backend/` | Placeholder for the planned FastAPI backend |
| `deploy/terraform/` | GCP demo infrastructure and VM setup |

Preview data stays in IndexedDB in the browser, or AsyncStorage and app-owned
photo files on Android. Reloads retain assessments and checklist actions.
Confirmed deletion removes the selected assessment and its associated photos.

See the [frontend development guide](docs/frontend-development.md) for more
detail, [demo notes](docs/demo.md) for verified behavior and pending device
checks, and [CONTEXT.md](CONTEXT.md) for product requirements and the planned
backend architecture.

See the [backend infrastructure guide](deploy/README.md) for Terraform provisioning,
HTTPS, storage access, and teardown. Provisioning infrastructure
does not implement or deploy the assessment API.
