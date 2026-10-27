# Frontend development

The frontend lives in `mobile/` and uses Expo SDK 57, React Native, and
TypeScript. The interactive preview works without a backend or API credentials.
Its results are predefined examples, not analysis of your selected photo.

## Start in this checkout

From the repository root in Bash (including WSL):

```bash
source scripts/frontend-env.sh
cd mobile
npm run web
```

Open the localhost URL printed by Expo in your browser. Expo Router pages live
in `mobile/app/`; shared UI, state, service, and storage code live in `mobile/src/`.
Expo refreshes the running app as you save.

Start with a room, select a photo or bundled sample, optionally select household
profiles, and create a sample assessment. Use **Preview** in the development
header to choose a scenario for a fresh demo, exercise failure/retry states, or
reset local data. Scenario changes do not change an existing assessment.

Browser photos and assessment data persist in IndexedDB. Android metadata uses
AsyncStorage, with selected photos copied into the app's document directory.
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
temporary public URL. Keep the terminal running and stop it with Ctrl+C when done.
An Android emulator is optional. `npm run android` requires an independently
configured Android SDK, adb, and a running emulator; these are not installed by
this setup. Browser preview and Expo Go do not require Android Studio.

## Install on another machine

Install Node.js 24 LTS (the pinned version is in `.nvmrc`), then run:

```bash
cd mobile
npm ci
npm run web
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
Playwright starts or reuses a local Expo server on port 8081. Tests run at phone
and desktop widths; screenshots and failure traces go into ignored `.tools/`.
Physical-device checks and observed limitations are recorded in `docs/demo.md`.

The lockfile currently reports eight dependency advisories: three high and five
moderate, involving Expo CLI, Router URL parsing, and tunnel support.
They remain unresolved. Do not apply `npm audit fix --force` blindly: its
suggested Expo downgrade would change the selected SDK.

## Backend integration

The backend and its API contract have not been implemented yet. No environment
variables are needed to develop this preview. `src/api/preview-service.ts`
isolates the simulated operations for later replacement. When integrating FastAPI, a phone
will need a reachable backend address rather than `localhost` (which refers to
the phone itself). Keep Muse credentials on the backend. Expo's
`EXPO_PUBLIC_*` variables are included in client bundles and must never hold
secrets.

Official references: [Expo setup](https://docs.expo.dev/get-started/create-a-project/)
and [Expo CLI](https://docs.expo.dev/more/expo-cli/).
