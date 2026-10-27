# Frontend development

The frontend lives in `mobile/` and uses Expo SDK 57, React Native, and
TypeScript. The starter screen works without a backend or API credentials.

## Start in this checkout

From the repository root in Bash (including WSL):

```bash
source scripts/frontend-env.sh
cd mobile
npm run web
```

Open the localhost URL printed by Expo in your browser. Edit `mobile/App.tsx`
to change the starter screen; Expo refreshes the running app as you save.
Use `src/components/`, `src/hooks/`, `src/api/`, and `src/storage/` for shared code.
The empty `app/` folder is reserved for future screens; this starter uses
`App.tsx` and does not install Expo Router.

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
npx expo install --check
npx expo export --platform web
```

Build output is ignored by Git. Android bundling can be checked with
`npx expo export --platform android` without installing an Android SDK.

At setup, TypeScript checking and web/Android exports passed. `npm audit`
reported five advisories: three high-severity entries through Expo CLI's Zod
dependency and two moderate entries through tunnel support's UUID dependency.
The suggested Expo fix is a major downgrade, and tunnel support has no automatic
fix. These remain unresolved; review upstream updates before deployment.

## Backend integration

The backend and its API contract have not been implemented yet. No environment
variables are needed to develop this starter. When integrating FastAPI, a phone
will need a reachable backend address rather than `localhost` (which refers to
the phone itself). Keep Muse credentials on the backend. Expo's
`EXPO_PUBLIC_*` variables are included in client bundles and must never hold
secrets.

Official references: [Expo setup](https://docs.expo.dev/get-started/create-a-project/)
and [Expo CLI](https://docs.expo.dev/more/expo-cli/).
