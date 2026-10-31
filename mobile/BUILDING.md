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

## Keeping the Firebase API key out of `eas.json`

Cloud builds cannot read `.env`: it is gitignored, so EAS does not upload it,
and `EXPO_NO_DOTENV=1` disables it anyway. Store the key as an EAS environment
variable instead. The `preview` profile sets `"environment": "preview"`, and
`production` sets `"environment": "production"`, so builds load the matching
variables automatically. `simulator` extends `preview` and uses the same
environment.

`scripts/build_pkg.sh` at the repository root automates steps 1, 2, and 4
and warns while step 3 is still pending; it never edits `eas.json`:

```sh
scripts/build_pkg.sh                  # Android APK (default)
scripts/build_pkg.sh ios              # or: all, store, ios-simulator
scripts/build_pkg.sh --skip-key-sync  # key already in EAS
```

To run the steps by hand:

1. From `mobile/`, signed in to EAS, copy the key from the root `.env` into EAS
   without printing it:

   ```sh
   npx --yes eas-cli@latest env:set \
     --name EXPO_PUBLIC_FIREBASE_API_KEY \
     --value "$(grep '^EXPO_PUBLIC_FIREBASE_API_KEY=' ../.env | cut -d= -f2-)" \
     --environment preview --environment production \
     --visibility sensitive
   ```

   `sensitive` hides the value in the EAS dashboard and build logs. `env:set`
   creates or updates the variable, so rerun it to change the key later.

2. Confirm it exists:

   ```sh
   npx --yes eas-cli@latest env:list --environment preview
   npx --yes eas-cli@latest env:list --environment production
   ```

3. Delete the `EXPO_PUBLIC_FIREBASE_API_KEY` line from the `preview` profile's
   `env` block in `eas.json`, so the EAS environment variable is the only
   source of the key. The project ID, auth domain, and app ID are identifiers,
   not secrets, and can stay.

4. Run a build (for example `npm run build:android`) and check that sign-in
   works in the installed app.

Removing the line does not remove the key from earlier git commits. If that
history is a concern, rotate the key and repeat step 1 with the new value.

`EXPO_PUBLIC_*` values are compiled into the app bundle, so anyone with the
installed app can extract the key. This is expected for a Firebase web API key,
which identifies the project rather than granting access. Protect it by
restricting the key in Google Cloud Console (to the `com.homesafetyai.mobile`
app and the APIs it uses) and by relying on Firebase Authentication and backend
authorization.

The application identifier on both platforms is `com.homesafetyai.mobile`.
Review this before the first store publication. Store builds increment their
build numbers using EAS remote version management.

Build reference: [Android APKs](https://docs.expo.dev/build-reference/apk/),
[iOS internal distribution](https://docs.expo.dev/build/internal-distribution/).
