# Account authentication and assessment ownership

Approved design: 2026-10-29, following the authentication grilling session.
Deliverable: specification only. Application implementation and cloud changes are subsequent work.

## Problem and outcome

The app currently authorizes requests with a shared demo bearer token and scopes
records by an installation-generated device ID. These are not authenticated user
identities. Introduce managed accounts so users can sign in on Android and iOS,
recover access, and reopen their latest assessment on another device. Only an
assessment's authenticated owner may access or change it or its associated data.

Use Google Cloud Identity Platform with Firebase Authentication SDKs. These are
one managed authentication stack, not separate account databases. Google manages
password verification, account creation, ID tokens, refresh, email verification,
and password-reset emails. Our app supplies the screens and integrates the SDK;
FastAPI verifies identities and enforces authorization. Do not implement a custom
password database, token issuer, or password-reset mechanism.

## Agreed scope

- Open email/password registration. Accounts are required from the beginning;
  anonymous authentication and invitation allowlists are excluded.
- Require verified email before accessing assessment features, on client and server.
- Native Expo login, sign-up, verification, password-reset, and account screens.
- Persistent sessions, sign-out, secure credential persistence, and account-isolated
  local state.
- UID-owned assessments, findings, submissions, photos, highlights, and masks.
- Same-account access to the latest assessment across installations and platforms.
- Account deletion, including retryable cleanup of associated server data.
- Authentication configuration, local emulation, deployment integration, documentation,
  and meaningful automated and device-level checks.

Explicitly excluded: social sign-in, MFA, email-address changes, guest access,
per-account AI quotas, live synchronization, offline sign-in,
offline upload queues, automatic legacy-data import, custom email-action pages,
automatic deep-link return from email actions, and store publication.

Open registration does not make paid AI usage bounded. Per-account usage limits
were explicitly deferred to separate work; do not add them to this feature.
Provider-managed authentication protections and quotas still apply.

Home and account-scoped history are added by
[`home-history/spec.md`](../home-history/spec.md), which supersedes latest-only
navigation in this spec. Authentication and account isolation remain unchanged.

## Existing implementation and constraints

- `mobile/app/_layout.tsx` mounts assessment state without an authentication gate.
- `mobile/src/hooks/preview-context.tsx` initializes a backend client from a
  persistent device identity and loads assessment state.
- `mobile/src/api/backend-client.ts` sends `X-Device-ID` and an optional shared
  demo bearer token, including for remote photo requests.
- `mobile/src/api/config.ts` keys cached backend state by API URL, not account.
- `mobile/src/storage/persistence.ts` and `.web.ts` persist assessment state.
- `backend/app/api/routes.py` uses shared-token authorization and a UUID device
  dependency. Firebase UIDs must not be constrained to UUID format.
- `backend/app/storage/repository.py` and `photos.py` store records and objects
  under `devices/{device_id}/assessments/...`.
- `backend/app/assessments/service.py` already scopes repository operations and
  validates photo membership against the parent assessment. Retain those protections
  while changing the trusted owner identity.
- `backend/app/annotations/dispatch.py` and persisted annotation work carry device
  identity. Internal worker routes use Google service-account OIDC authentication.
- `backend/app/config.py`, `backend/compose.yaml`, `deploy/terraform/main.tf`, and
  `scripts/deploy-gcp.py` contain configuration and operational flows that currently
  assume the demo token and/or lack Firebase Auth configuration.

`CONTEXT.md` currently excludes accounts and cross-device synchronization and
describes device scoping and a shared demo token. This spec intentionally supersedes
those account, ownership, and transport-authentication decisions during implementation.
Reopening server data on another device is included; live synchronization remains
excluded. Update the context during implementation so it reflects this distinction.

ADR 0001's backend-only access to Firestore and private GCS remains compatible.
Preserve the durable, independently dispatched highlight behavior in ADRs 0002
and 0003. Do not replace machine authentication with user authentication.

## Identity and authorization contract

1. Register the application(s) in the intended Firebase/GCP project and enable
   Identity Platform email/password authentication. Keep client and server project
   configuration aligned. Do not create a second identity store.
2. The client obtains an ID token from the Firebase SDK and sends
   `Authorization: Bearer <ID token>` on each protected API request. Obtain current
   credentials at request time; do not capture one token in a long-lived client.
3. FastAPI uses the Firebase Admin SDK to verify signature, issuer, audience,
   expiry, and project, and obtains `uid` from the verified result. Check revoked
   sessions and disabled/deleted accounts rather than accepting them until token
   expiry. Reject anonymous identities for this account-only feature.
4. For assessment access, require `email_verified` from verified token claims.
   After email verification, the client reloads the Firebase user and forces an
   ID-token refresh before retrying access.
5. Never accept `owner_uid`, email, or `X-Device-ID` from the client as proof of
   ownership. The device identifier may remain for diagnostics only if needed.
6. Assign ownership on the server when creating an assessment. Scope latest/read,
   updates, deletion, photo uploads/downloads, submissions, follow-ups, reviews,
   highlight results, masks, retries, and feedback to that verified UID.
7. Resolve child resources through their owned parent assessment. A guessed object
   path or finding/photo/highlight identifier must not grant access. Cross-owner
   resource requests return the same 404 response as missing resources.
8. Return 401 for absent/invalid/revoked identity, 403 with a stable machine-readable
   reason for an authenticated but unverified account or deletion in progress.
   Do not disclose another account's identifiers or metadata in errors.
9. Remove the demo token and device-ID authorization fallback from user routes.
   A valid old demo token must not bypass authentication after cutover.

Cloud Run remains reachable by mobile clients, with user authentication enforced
inside FastAPI. Cloud Run IAM invocation authentication is not Firebase end-user
authentication. Keep internal annotation work/recovery routes protected by their
existing verified service-account identity and allowlist. Explicitly document any
public health/liveness endpoint; it must disclose no user data or credentials.

All Firestore and GCS access remains backend-only. Server libraries operate with
service credentials, so ownership checks in FastAPI/repositories are mandatory;
client security rules alone cannot enforce this backend's user isolation. Keep
photos and masks private; authorized API retrieval is the default delivery path.

## Storage and legacy records

Use a separate UID-owned namespace, such as
`users/{uid}/assessments/{assessment_id}`, for new Firestore records and GCS objects.
Persist an explicit server-controlled `owner_uid` on assessments. Account state,
including deletion state, belongs in a durable user record. Treat UIDs as opaque
identifiers and construct safe storage paths without applying UUID validation.

Carry the trusted owner through assessment services, models, photo storage,
highlight dispatch, recovery, and worker payloads. Worker authorization remains
machine-based; the owner in its trusted task payload scopes the work. Workers
must also check the durable account deletion state before publishing results.

Leave existing `devices/...` server data untouched. New accounts start with empty
histories; do not attach old data by matching a submitted device ID. Ignore and
remove legacy local caches from the active account workflow so they are not shown
to a newly signed-in user. Any later legacy-data import requires a separate trusted
administrative migration design.

Existing legacy worker payloads must be versioned or handled explicitly during
cutover: never reinterpret a legacy device ID as a Firebase UID, never expose
legacy outputs through account endpoints, and never delete legacy data as part
of a new account's deletion.

## App navigation and account flows

Authentication bootstrap precedes backend assessment initialization. Model at least
these states: initializing, signed out, signed in/unverified, signed in/verified,
reauthentication required, and account deletion pending. Do not flash cached room
photos or assessment screens while resolving identity.

### Login and registration

- Login has visible Email and Password labels, a password visibility toggle,
  `Sign in`, `Forgot password?`, and `Create account` actions.
- Sign-up collects only email/password information needed for this flow. Enforce
  the configured provider password policy with helpful validation; Google remains
  authoritative. Do not persist passwords in app state, logs, analytics, or caches.
- Registration creates the managed account, sends a verification email, and shows
  the verification screen. If email delivery fails after account creation, retain
  the account session and offer resend rather than creating another account.
- Verification has resend, `I've verified my email`/refresh status, and sign-out
  actions. Prevent duplicate requests and handle provider cooldowns without
  presenting a failed send as success.
- Use the provider's browser verification action page initially. Explain that the
  user should return to the app and refresh status. Expired/invalid links have a
  clear resend/recovery path.
- Password reset calls the managed SDK to send the reset email and uses the
  provider's browser action page. Give a neutral confirmation that does not expose
  whether an email has an account. Users return to login after resetting.
- Enable provider email-enumeration protection where supported; use neutral login
  errors without leaking account existence or raw SDK exceptions.

### Persistent sessions, logout, and multiple devices

- Restore the managed session across normal app restarts. Let the SDK handle
  refresh; do not invent a refresh-token endpoint or duplicate token lifecycle.
- Never place authentication tokens or secrets in AsyncStorage, IndexedDB
  assessment records, or the existing assessment cache. Validate a platform-secure
  persistence implementation for Android/iOS before committing to an SDK/runtime.
  The Firebase JS SDK supports Expo Go, but its usual AsyncStorage persistence is
  not sufficient for this requirement. Verify a secure persistence adapter, or
  use a supported native SDK/development-build path with inspected persistence.
  Do not promise Expo Go compatibility before that check passes. Existing web
  preview/testing must have an explicit supported auth persistence strategy and
  must not silently store native credentials in its assessment cache.
- Obtain tokens for image/mask requests through the authenticated API client too;
  do not put bearer tokens in URLs.
- Namespace assessment caches, drafts, and photo state by identity project, API
  environment, and UID. Clear the current account's local app-managed data on
  sign-out, including app-managed downloaded images. Do not delete originals from
  the user's camera roll.
- Cancel or disregard old in-flight responses and isolate task subscriptions after
  identity changes. Invalidate memory caches and navigation history so Back cannot
  show another account's data. Do not automatically upload a former account's draft.
- An invalidated session returns to login with a recovery message and hides account
  data. Network failure is distinct from sign-out: show retry and do not silently
  erase valid local work simply because the network is unavailable.
- A verified account on either platform opens Home and can browse retained server
  assessments as specified in `../home-history/spec.md`. Refresh/reopen retrieves
  updates from other devices. Do not add live listeners or an offline mutation queue.

## Account and data deletion

The account screen displays the signed-in email, sign-out, and a distinct destructive
`Delete account` action. Explain that deletion includes assessments and associated
photos/highlights, requires the password again, and has no recovery grace period.
Do not report success while cleanup is merely pending.

Deletion is server-orchestrated and idempotent:

1. Reauthenticate with the Firebase SDK, obtain a fresh token, and submit deletion.
   The backend independently enforces recent `auth_time` (within five minutes).
   Permit authenticated unverified users to delete their own account too.
2. Durably mark the account as deleting before cleanup, block ordinary reads and
   writes on all devices, and invalidate access. Gate all protected user operations
   and internal workers on this state so still-running jobs cannot recreate data.
3. Queue durable cleanup using trusted service credentials. Delete all account-owned
   assessment documents, nested data, original/submission/review photos, masks, and
   associated highlight data. Coordinate with running jobs and sweep late outputs;
   a one-time delete followed by an unchecked worker write is not sufficient.
4. Delete the managed identity only after data cleanup succeeds. Retain sufficient
   minimal operational deletion state to retry failures independently of any user
   session. Treat already-deleted data or identity as successful on retry.
5. Clear local account state and present completion only when completion is known.
   For asynchronous cleanup, show an honest pending state; interruption, logout,
   or loss of the initiating token must not prevent server cleanup from completing.

Deletion status must be pollable using a narrowly scoped, non-logged operation
receipt or another explicit mechanism that remains usable after session revocation.
It must reveal only that deletion operation's status, not permit assessment access.
Define and test receipt expiry and recovery behavior during implementation. Cleanup
failures are observable and retryable; they must not reopen access or strand photos
because the identity was deleted first.

## UI design and required skills

Reading this as: a home safety app for households, with a calm, modern interface,
targeting iOS and Android. Dials: design variance 3/10, motion intensity 2/10, visual
density 3/10. Match the app's existing tokens and brand accent rather than redesigning
the whole app.

Use `.codex/skills/mobile-design/SKILL.md` and its relevant form, accessibility,
navigation, and platform references during UI implementation and review. The user
also requires the Expo plugin: discover and use that exact plugin before UI work.
At specification time the plugin was not available in connected tools, local skill
directories, or plugin search results. Its exact availability is an implementation
dependency; do not claim it has been used or silently substitute an unrelated tool.

- A compact app identity and clear screen heading lead into a focused form and
  one obvious primary action. Avoid a website-style hero or decorative animation.
- Keep labels visible; support email keyboards, Next/Submit focus flow, password
  managers, autofill, and paste. A keyboard-aware scrolling layout must keep the
  focused field and action reachable.
- Cover idle, focus, pressed, disabled, submitting, success, offline, field error,
  provider failure, expired-link, expired-session, and deletion-pending states.
  Preserve appropriate input on recoverable errors; passwords remain transient.
- Provide accessible names, roles, state announcements, logical focus order,
  scalable text, WCAG AA contrast, and minimum 44pt iOS/48dp Android touch targets.
- Respect safe areas, gesture navigation, orientation, compact windows, and larger
  tablet windows. Use platform-appropriate autofill/back behavior. Support long
  text without clipping; no new localization system is required.
- Use restrained native transitions and respect reduced motion. Layout and semantic
  state clarity take priority over decorative effects.

## Configuration, development, and deployment

- Add explicit client Firebase configuration and backend project configuration.
  Public Firebase client configuration is not an authorization secret. Keep Admin
  credentials server-only; use the Cloud Run service account/ADC rather than
  distributing service-account keys to the app.
- Provision/document Identity Platform, required APIs, provider settings, email
  templates/action domains, password policy, and Firebase app registration in the
  existing deployment workflow. Separate emulator/local and cloud configurations.
- Add Firebase Auth emulator support alongside Firestore/GCS local services. Support
  verification/reset flows and multi-user tests locally. Production startup must
  reject Auth emulator configuration, including accidental emulator environment
  variables that would allow acceptance of emulator-issued tokens.
- Replace demo-token requirements, secret handling, phone environment generation,
  protected health checks, and deployment smoke checks. Do not retain a production
  bypass for convenience. State which probes are public and which use test users.
- Document signed-in local development, email verification, password recovery,
  deployment configuration, new owner namespaces, and the intentional legacy-data
  boundary. Keep simulated developer preview state separate; it must never expose
  an unauthenticated path into real user data.
- Preserve correlation IDs and useful auth/deletion error categories in logs.
  Never log passwords, authorization headers, tokens, email action codes, image
  payloads, or deletion status receipts.

## Acceptance and verification

Use Auth emulator integration tests and existing backend/mobile test infrastructure;
do not rely only on mocked token decoding. Include negative authorization tests.

1. A new user registers, receives verification, signs in, verifies, refreshes the
   token, and reaches assessment features. Unverified direct API requests fail.
2. Reset email uses neutral confirmation; reset completion allows the new password
   and the old password fails. Invalid credentials and provider/network failures
   have recoverable UI states without leaking secrets.
3. Missing, malformed, expired, wrong-project, revoked, disabled/deleted, and
   anonymous identities cannot access account-owned resources. Legacy demo tokens
   and arbitrary device headers cannot bypass the gate.
4. Users A and B can each create assessments. B cannot read/update/delete A's
   assessment, create a submission against it, retrieve its photos/masks, or invoke
   its highlight retry/feedback endpoints. Test the inverse and guessed child IDs.
5. Signing out during upload, analysis, image fetching, or refresh does not leak
   late results into the next account. Restart and account switching do not expose
   another account's drafts, photos, or assessment. Signed-out Back navigation
   cannot reveal private screens.
6. Same-account sign-in on a second device reopens the latest server assessment;
   another account starts empty. Legacy device-owned records remain untouched and
   inaccessible regardless of client-supplied device IDs.
7. Secure session restoration works on both platforms. Verify credential storage
   and logs rather than assuming SDK defaults meet the requirement.
8. Deletion requires recent reauthentication and explicit confirmation, blocks
   access on other devices immediately after durable acceptance, removes all
   account-owned data, and completes identity deletion. Test unverified accounts,
   repeated requests, partial database/object/auth failures, interrupted clients,
   expired receipts, and worker writes racing with cleanup.
9. Internal workers still require authorized service-account OIDC tokens. User ID
   tokens cannot invoke them; workers cannot recreate a deleting account's data.
10. Production rejects emulator settings and cannot fall back to demo auth.
    Local emulator-backed registration, verification/reset, assessment ownership,
    and deletion are documented and executable without production credentials.
11. On representative Android and iOS devices/builds, check keyboard avoidance,
    autofill, password visibility, text scaling, VoiceOver/TalkBack, small/large
    windows, interrupted sessions, and the browser-email-to-app return flow.

Specification verification: repository integration points were inspected and the
official sources below were consulted. No UI, runtime persistence adapter, deployed
Identity Platform configuration, or real-device flow has been implemented or tested
as part of this document.

## Implementation sequence

1. Resolve the requested Expo plugin dependency; validate SDK/runtime and secure
   persistence support. Add managed identity configuration and local emulation.
2. Implement backend token verification, UID storage, full ownership enforcement,
   and internal-worker compatibility with cross-account integration tests.
3. Implement authentication screens and navigation gates, token-aware API/photo
   access, session persistence, cache isolation, and latest-assessment access.
4. Implement account deletion and durable cleanup, including concurrency/failure
   coverage, then integrate deployment scripts and smoke tests.
5. Update context/setup/demo documentation, run relevant automated checks, and
   validate the full flow on both target platforms before release.

## Primary references

- [Identity Platform and Firebase Authentication comparison](https://docs.cloud.google.com/identity-platform/docs/product-comparison)
- [Expo Firebase integration and SDK/runtime choices](https://docs.expo.dev/guides/using-firebase/)
- [Managed email/password authentication](https://firebase.google.com/docs/auth/web/password-auth)
- [Email verification, reset, and reauthentication](https://firebase.google.com/docs/auth/web/manage-users)
- [Admin ID-token verification](https://firebase.google.com/docs/auth/admin/verify-id-tokens)
- [Session revocation](https://firebase.google.com/docs/auth/admin/manage-sessions)
- [Cloud Run end-user authentication](https://docs.cloud.google.com/run/docs/authenticating/end-users)
- [Identity Platform prebuilt web interface](https://docs.cloud.google.com/identity-platform/docs/how-to-integrate-with-pre-built-interface)

## Decision record from the interview

1. Email/password accounts, sign-up, and reset: yes; managed Google mechanism.
2. Fresh account histories; legacy server data untouched: yes.
3. In-app account and data deletion: yes.
4. Expo screens backed by Firebase SDK: yes; use Expo plugin and mobile-design.
5. Verified email before assessment access: yes.
6. Registration: open to anyone.
7. Persistent sessions and local cleanup on sign-out: yes.
8. Latest assessment available across devices for the same account: yes.
9. Per-account AI limits: no; separate follow-up.
10. Consolidated scope, including deletion/recovery boundaries and spec-only work:
    confirmed by the user before this file was written.
