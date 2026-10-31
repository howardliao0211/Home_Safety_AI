# Downloadable mobile builds

Run these commands from `mobile/` with an Expo account signed in:

```sh
npx --yes eas-cli@latest login
npm run build:android
npm run build:ios
```

`npm run build:all` starts both platforms. EAS prints a build page and an
installation/download link when each build finishes. These are standalone
release builds; Expo Go and a running development server are not required.

| Command | Artifact | Installation |
| --- | --- | --- |
| `npm run build:android` | APK | Download on Android and allow installation from the browser. |
| `npm run build:ios` | Signed IPA | Install through the EAS link on registered iPhones/iPads. |
| `npm run build:ios:simulator` | Simulator app archive | Install on an iOS Simulator on a Mac; cannot install on an iPhone. |
| `npm run build:store` | Android AAB and iOS IPA | Upload separately to Google Play and App Store Connect/TestFlight. |

For the first Android build, let EAS generate and manage the signing keystore.
For physical iOS devices, a paid Apple Developer membership and distribution
signing credentials are required. Register each device before building:

```sh
npx --yes eas-cli@latest device:create
npm run build:ios
```

Sign in to Apple through the EAS prompt on your own terminal. Adding a device
after a build requires a new build or `eas build:resign`. For distribution to a
wider test group, use the production profile and TestFlight instead.

The `preview` profile in `eas.json` contains the public cloud API and Firebase
client settings, copied from the root `.env` during setup. The other profiles
inherit them. Update those settings if the backend or Firebase application
changes. `EXPO_NO_DOTENV=1` prevents a developer's local `.env` (which may point
to localhost) from overriding build configuration. EAS dashboard environment
variables should not add an authentication emulator or development overrides.
Firebase client configuration is public and embedded in the app; backend
credentials must never be added here.

The application identifier on both platforms is `com.homesafetyai.mobile`.
Review this before the first store publication. Store builds increment their
build numbers using EAS remote version management.

Build reference: [Android APKs](https://docs.expo.dev/build-reference/apk/),
[iOS internal distribution](https://docs.expo.dev/build/internal-distribution/).
