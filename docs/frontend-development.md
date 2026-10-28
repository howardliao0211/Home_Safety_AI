# Frontend development

The frontend lives in `mobile/` and uses Expo SDK 57, React Native, and
TypeScript. API mode is the default and submits photos to the backend for
analysis. Explicit preview mode works without a backend or API credentials;
its results are predefined examples, not analysis of your selected photo.

## Start in this checkout

Start the storage emulators and API using [the backend guide](../backend/README.md#start-locally).
Then, from the repository root in another Bash terminal (including WSL):

```bash
source scripts/frontend-env.sh
cd mobile
cp .env.example .env
npm run web
```

Open the localhost URL printed by Expo in your browser. Expo Router pages live
in `mobile/app/`; shared UI, state, service, and storage code live in `mobile/src/`.
Expo refreshes the running app as you save.

Start with a room, select a photo or bundled sample, optionally select household
profiles, and create an assessment. To run without the backend, use
`EXPO_PUBLIC_DATA_SOURCE=preview npm run web` instead. In preview mode,
use **Preview** in the development
header to choose a scenario for a fresh demo, exercise failure/retry states, or
reset local data. Scenario changes do not change an existing assessment.

API assessments and photos persist through the backend's Firestore/GCS stores.
The latest assessment is restored from the API, including when its local cache
is absent. A persistent device UUID scopes the installation's records; clearing
that identity loses access to those records. API and preview local state use
separate namespaces. Browser drafts and cached photos persist in IndexedDB.
Android metadata uses AsyncStorage, with selected photos copied into the app's document directory.
Confirmed assessment deletion removes its records and photos; starting another
assessment retains earlier records. No history browser is included.

The activation script selects the Linux Node.js 24.22.1 runtime installed in
this checkout's ignored `.tools/` directory. Source it in each new terminal.
This avoids accidentally running Windows npm from WSL. No system-wide Node
installation or shell profile was changed.

## Run on an Android phone

Install Expo Go on your Android phone, then run from `mobile/`:

```bash
npm start
```

For API mode, bind Uvicorn to `0.0.0.0` and set `EXPO_PUBLIC_API_URL` in
`mobile/.env` to `http://<development-machine-LAN-IP>:8000`. Use
`http://10.0.2.2:8000` for an Android emulator. Restart Expo after changes.
Scan the terminal's QR code with Expo Go. The phone must be able to reach the
development machine on the same network. SDK 57 is selected to follow Expo's
current physical-device guidance; use a matching Expo Go version from
<https://expo.dev/go>.

WSL networking or a firewall may prevent a phone from reaching the LAN URL.
For that case, tunnel support is installed locally:

```bash
npm run start:tunnel
```

Tunneling needs internet access and exposes the development server through a
temporary public URL. This tunnels Expo only, so API mode still needs a backend
address reachable from the phone. Keep the terminal running and stop it with Ctrl+C when done.
An Android emulator is optional. `npm run android` requires an independently
configured Android SDK, adb, and a running emulator; these are not installed by
this setup. Browser preview and Expo Go do not require Android Studio.

## Install on another machine

Install Node.js 24 LTS (the pinned version is in `.nvmrc`), then run:

```bash
cd mobile
npm ci
EXPO_PUBLIC_DATA_SOURCE=preview npm run web
```

The project-local Node runtime is not committed. If you already have Linux Node
installed, the activation script uses it when the local runtime is absent.

## Check changes

```bash
npm run typecheck
npm test
npm run test:e2e
npx expo install --check
npx expo-doctor
npx expo export --platform web --platform android
```

Build output is ignored by Git. Android bundling can be checked with
`npx expo export --platform android` without installing an Android SDK.

For browser tests, first install Chromium with `npx playwright install chromium`.
Playwright starts its own preview Expo server on port 8083. Tests run at phone
and desktop widths; screenshots and failure traces go into ignored `.tools/`.
Physical-device checks and observed limitations are recorded in `docs/demo.md`.

For connected browser journeys, install backend dependencies and start the
storage emulators as described in the backend guide, then run
`npm run test:e2e:api`. It starts its own API on 8001 and Expo on 8082. The
fixture exercises real HTTP and emulator storage with a deterministic model;
it does not call Muse or Groq or measure detection accuracy. It uses separate device
IDs and deletes its test assessments. Keep ports 8001, 8082, and 8083 free.

## Backend integration

`mobile/.env.example` documents the public client settings:

| Variable | Behavior |
| --- | --- |
| `EXPO_PUBLIC_DATA_SOURCE` | `api` by default; `preview` enables fixtures explicitly |
| `EXPO_PUBLIC_API_URL` | Defaults to `http://127.0.0.1:8000`; use a reachable host on Android |
| `EXPO_PUBLIC_DEMO_TOKEN` | Match the backend's `DEMO_BEARER_TOKEN` if configured |

The shared demo token is client-visible MVP access control. Keep Groq and Muse
API credentials on the backend. Expo's `EXPO_PUBLIC_*` variables are included
in client bundles and must never hold model keys. Production web origins need
an explicit backend `CORS_ORIGINS` allowlist; local port 8081 is allowed by default.

The API client maps DTOs, uploads retained photos, restores server state, and
loads private photos using device and bearer headers. Initial and linked
analysis failures preserve evidence and require a manual retry with the same
IDs. Submitted evidence is immutable; a user-requested photo review remains
available separately. Failed status saves stay visible without publishing a
successful local change. API connection failures show Retry connecting and
never silently switch to preview results.

Official references: [Expo setup](https://docs.expo.dev/get-started/create-a-project/)
and [Expo CLI](https://docs.expo.dev/more/expo-cli/).
