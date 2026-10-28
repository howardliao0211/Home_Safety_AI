# Accounts and assessment ownership

The app uses Google Cloud Identity Platform through Firebase Authentication.
Email/password sign-in and verified email are required for assessment access.
FastAPI verifies Firebase ID tokens with revocation/disabled-account checks; it
never trusts a device header. `/health` is public liveness with only `status: ok`.
Internal annotation/recovery routes still require allowlisted service-account OIDC.

## Local development

Copy `.env.example` into the ignored root `.env` and supply your model key.
Run `docker compose -f backend/compose.yaml up -d` for Auth (9099), Firestore
(8080), and GCS (4443). Auth uses the Firebase CLI and persists emulator exports
in its own Docker volume. For an already-running external Auth emulator, use
`docker compose -f backend/compose.yaml up -d firestore photos` instead.

Run the API as described in `backend/README.md`, and run a separate durable
recovery process even if highlights are disabled:

```sh
cd backend
uv run python -m app.annotations.local_worker
```

Set `FIREBASE_AUTH_EMULATOR_HOST=127.0.0.1:9099` on the backend and
`EXPO_PUBLIC_AUTH_EMULATOR_URL=http://127.0.0.1:9099` on browser clients. Use the
host's reachable LAN address or an appropriate emulator host alias on phones;
never point a phone at its own localhost. Client/backend project IDs must match
(`home-safety-local`). Auth emulator email-action URLs appear in emulator output;
open the latest verification/reset link, then return to the app and refresh or
sign in. Auth emulator emails are not delivered to real mailboxes.

```sh
cd backend
RUN_EMULATOR_TESTS=1 uv run pytest
cd ../mobile
npm run typecheck
npm test
npm run test:e2e:api
```

The connected browser suite uses real Auth/Firestore/GCS emulators and a deterministic
model fixture. It never calls paid models. The isolated simulated preview remains
`EXPO_PUBLIC_DATA_SOURCE=preview` and has its own assessment state.

## Persistence and identity changes

Native clients use Firebase JS SDK 12.7's public `getReactNativePersistence`
interface with an Expo SecureStore adapter, rather than AsyncStorage. Inspection
of SDK persistence confirms its injected storage handles the serialized user
record (including refresh credentials). SecureStore 58.0.2 uses Android Keystore
AES/GCM encryption and iOS Keychain; the adapter selects
`AFTER_FIRST_UNLOCK_THIS_DEVICE_ONLY` on iOS. Chunked records avoid small Keychain
item limits, and a final manifest switches the committed session atomically.
A secure-storage preflight blocks bootstrap on failure. No separate token refresh
lifecycle is implemented. This source inspection and adapter tests do not replace
native-device credential inspection and restart testing.

Web uses Firebase's `browserSessionPersistence`: credentials live in the tab's
sessionStorage, separate from assessment IndexedDB, and closing the tab ends
persistence. Native tokens never enter assessment records or AsyncStorage.
Firebase obtains current tokens for API, image, and mask requests; no tokens appear
in URLs. Native device/Expo Go compatibility remains unverified until tested on
both target platforms. Production builds must include the SecureStore config plugin.

Assessment cache and photo directories include identity project, API origin, and
UID. Logout disposes the client, rejects queued/late state writes, drains local
writes, clears that account's app-managed cache/photos, and signs out the SDK.
The camera roll is never changed. Private images disable disk caching. Network
failures retain the session and local work with a visible retry action.

## Server storage and deletion

New documents and objects use `users/{encoded_uid}/assessments/...`; the path
component is unpadded URL-safe base64 of the UTF-8 opaque Firebase UID. Each
assessment stores a server-controlled `owner_uid`. Existing `devices/...` data
is intentionally untouched and never imported. Worker payloads require version 2
and `owner_uid`; legacy device payloads are rejected, not reinterpreted.

Deletion accepts a token with `auth_time` no older than five minutes, including
unverified accounts. Acceptance durably fences the user before attempting
revocation. Firestore transactions read the account fence along with every
assessment mutation, including bounded worker publication. Photo uploads check
before and after upload and remove deletion-racing output.

The durable Firestore deletion intent is swept by the service-authenticated
Scheduler recovery route (and the independent local worker). Cleanup removes
objects, waits 330 seconds to exceed the longest work lease, recursively removes
assessment documents, sweeps objects again, and only then deletes the identity.
Failures leave the tombstone in place and are retried on the next sweep. Completed
account tombstones remain in the sweep to remove late outputs from paused jobs.
`account_cleanup_failed` logs contain error categories, never credentials/receipts.

A random 256-bit secret plus operation UUID permits status polling in the
`X-Deletion-Receipt` header at `POST /v1/account/deletion/status`, with no token.
Only the secret hash, owner, and seven-day expiry are persisted server-side.
Receipts grant no assessment access. Invalid receipts return 404; expired receipts
return 410. While the identity exists, sign in again, reauthenticate, and request
deletion to obtain a new receipt without restarting cleanup. If the identity has
already been removed and the receipt expired/lost, the app cannot attest to that
operation's completion: operational recovery is required. It must not show a
successful deletion without confirmation. Native receipts use SecureStore; web
receipts persist for the tab session. Receipt expiry never stops cleanup.

## Deployment

Terraform enables Identity Toolkit/Firebase APIs, email/password authentication,
and the backend Firebase Auth admin role. Import any already-managed Identity
Platform config before applying; do not create another identity project. Register
one Firebase **web app** in the same existing GCP project for this JS SDK client
on both native platforms and web. Copy its public `apiKey`, `appId`, `projectId`,
and `authDomain` to the corresponding `EXPO_PUBLIC_FIREBASE_*` settings. Admin
credentials remain ADC/service-account credentials on the backend.

The installed Google Terraform provider does not expose password-policy or email
privacy fields. After provisioning, run `scripts/deploy-gcp.py configure-auth`
with the normal backend Python environment to enable enumeration protection and
a required 12-character uppercase/lowercase/number/symbol password policy through
the official Identity Toolkit configuration API. Verify the settings in the console.
Keep provider-managed browser verification/reset action pages; configure authorized
domains and email sender/templates in Firebase Authentication before release.
There are no custom action pages, automatic email deep-link return, or social providers.

Configure the stable Cloud Run service URL as `annotation_worker_url` and apply
Terraform so Scheduler invokes `/internal/annotations/recover` every minute, even
when highlighting is disabled. Release/startup reject missing durable-worker
configuration. For first deployment, resolve the canonical Cloud Run origin from
the intended service name/project number/region before provisioning the schedule.

`release`, `verify`, `rollback`, and `phone-env` need
`HOME_SAFETY_SMOKE_ID_TOKEN` in the operator process: a current verified test-user
Firebase ID token for this project, never a service OIDC token. It is used in
memory for actual protected photo/assessment CRUD and removed fixture checks;
it is never written into phone settings. Rollback rejects legacy demo-token
revisions. Model keys remain numbered Secret Manager versions. Remove emulator
variables from cloud and mobile production configuration; backend production
startup rejects even an accidental `FIREBASE_AUTH_EMULATOR_HOST` environment variable.

## Release verification still required

On Android and iOS devices/builds, inspect encrypted credential storage and logs,
restart/restore/sign-out/account-switch flows, interrupted uploads and deletion,
password-manager/autofill behavior, keyboard avoidance, small/large windows,
large text, VoiceOver/TalkBack, password visibility, browser email actions and
manual return/refresh. This environment has no attached devices or native SDKs.
No cloud provisioning, real email delivery, native persistence validation, or store
publication is claimed by automated browser/emulator checks.

Sources: [Firebase token verification](https://firebase.google.com/docs/auth/admin/verify-id-tokens),
[Expo Firebase integration](https://docs.expo.dev/guides/using-firebase/),
[Expo SecureStore](https://docs.expo.dev/versions/latest/sdk/securestore/),
[Identity Platform password policy](https://docs.cloud.google.com/identity-platform/docs/password-policy),
[email enumeration protection](https://docs.cloud.google.com/identity-platform/docs/admin/email-enumeration-protection).
