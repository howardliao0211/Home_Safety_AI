# GCP account-authenticated phone test

For managed identity, emulator and native persistence setup, read
[authentication](../docs/authentication.md) first. Physical-device checks and cloud
identity provisioning must pass before release.

The owner runs Expo Go on Android, the development computer runs the Expo tunnel,
and FastAPI runs in project `home-safety-ai`, region `us-central1`. Keep resources
and data until explicit destroy. No automatic teardown is installed. Readiness
requires cloud auth/storage/TLS checks; real Muse and phone journeys are exploratory.

The API liveness endpoint is `/health`. Cloud Run reserves some URL paths ending
in `z`, so health checks use this path for both local and cloud deployments.

## Ownership and prerequisites

| Component | Owner |
| --- | --- |
| Infrastructure lifecycle, local image gate, private local state/backups | `scripts/terraform-gcp.py` |
| APIs, Artifact Registry, Firestore/GCS, service accounts/IAM, Tasks/Scheduler | Terraform configuration |
| Build/push, secret versions, Cloud Run revisions/traffic, verification, rollback, service deletion | `scripts/deploy-gcp.py` |
| Managed accounts and provider email actions | Identity Platform/Firebase in the same GCP project |

Install Docker, gcloud, Terraform >=1.14 and <2, uv/Python >=3.10 and pinned Node.
Sign in using `gcloud auth login`. The provisioning account needs API, storage,
registry, service account/IAM, secrets, Tasks/Scheduler and Firestore
permissions. Releases additionally need Cloud Run deployment/public invocation,
service-account usage, image upload and secret-version access. Terraform never
grants the operator permissions to itself. If Docker group membership was just
added, open a new shell or use `sg docker`.

All Terraform commands go through the wrapper, including init/plan/apply/destroy,
validate/fmt/show/output. Put `--account=EMAIL` before either CLI's subcommand to
override the active gcloud account. The wrapper passes a short-lived OAuth token
only through the environment. It inspects release state and reports a next release
command; it never silently builds, pushes or releases.

Cloud Run starts with 1 CPU, 2 GiB RAM, concurrency 8, minimum 0, maximum 2 instances,
and a 300-second timeout. Invocation is public; FastAPI verifies Firebase user ID
tokens and scopes records/photos by the verified UID. Production API docs
are disabled. Model credentials stay backend-only. The phone and highlight workers
use Cloud Run's generated `https://...run.app` service URL with managed HTTPS.

## Build and provision

### Guided deployment script

From the repository root, add the launcher to your shell's PATH once:

```bash
export PATH="$PWD/bin:$PATH"
deploy start
deploy stop
```

You can also use `./bin/deploy start` / `./bin/deploy stop`, or
`python3 scripts/deploy.py start` / `python3 scripts/deploy.py stop`.
The launcher works from any directory after PATH is configured. Keep this checkout
and its private Terraform state when moving between machines.

`scripts/deploy.py` automates provisioning, secrets, Muse releases, highlight
recovery, verification and the phone environment steps below. It
keeps the Terraform wrapper's saved-plan review and typed `apply` confirmations.
Install the prerequisite tools and sign in with `gcloud auth login` first; put
`MUSE_API_KEY` and `MUSE_MAIN_MODEL` in root `.env`.
Configure a verified Firebase test account once, in the same cloud project as the
deployment. In the private root `.env`, set `HOME_SAFETY_SMOKE_EMAIL`,
`HOME_SAFETY_SMOKE_PASSWORD`, and the cloud `EXPO_PUBLIC_FIREBASE_API_KEY`.
The script signs in through Firebase for fresh test tokens automatically; it
never writes those tokens to phone settings. A current `HOME_SAFETY_SMOKE_ID_TOKEN`
in `.env` or the environment is also supported and takes precedence.
Start checks these credentials before building images or provisioning resources.
First-time Firebase app registration and email verification are described in
[authentication setup](../docs/authentication.md).

```bash
python3 scripts/deploy.py start
```

Every successful `start` discovers the live Cloud Run service URL and writes it
to root `.env` as `EXPO_PUBLIC_API_URL`, together with API mode and the serving
Firebase project ID (no user token). It also applies that URL as the highlight worker target
before enabling segmentation. Repeated deployments and deployments after `stop`
refresh these values automatically.
Restart any running Expo process to load updated settings. To launch Expo after
deployment, or resume after a successful bootstrap:

```bash
python3 scripts/deploy.py start --start-expo
# Resume and keep the Expo tunnel running:
python3 scripts/deploy.py start --stage finish --start-expo
```

Stages are `all` (default), `bootstrap` (release and write phone settings), and
`finish` (discover/verify the service URL, configure highlight recovery, release,
and refresh phone settings). Use `start` for initial and repeated deployments.
`--model` overrides `.env`'s `MUSE_MAIN_MODEL`; `--account` is forwarded to both
existing wrappers.

The script saves non-secret settings in ignored, private
`deploy/terraform/deploy.tfvars.json`. Its plans explicitly load that file after
normal Terraform inputs, so its settings take precedence over conflicting tfvars.
When manually planning after using the script, include `-var-file=deploy.tfvars.json`
through the wrapper to retain these settings. Do not run other release/rollback
commands concurrently. `start` leaves resources/data in place on failure.
It does not run exploratory phone/model journeys or local
test suites; those remain separate checks below.

To stop, destroy all Terraform-managed infrastructure and the Cloud Run service:

```bash
python3 scripts/deploy.py stop
```

`stop` defaults to destruction, including persistent assessments and photos; it
does not pause resources. It displays a destroy plan and requires typing `destroy`
before removing Cloud Run and applying the plan. It loads the same private variable
file as `start`, initializes Terraform if needed, and requires only Python, Terraform
and gcloud. No uv, backend virtual environment, Docker image, model credentials or
test-user token is needed. Partial deployments without release outputs and repeated
stops are supported. Missing state is an error: restore a private backup rather than
assuming there is nothing to delete.
Identity Platform configuration and registered accounts remain: the Google
provider removes this configuration from state without deleting it in GCP
([provider implementation](https://github.com/hashicorp/terraform-provider-google/blob/v7.46.2/google/services/identityplatform/resource_identity_platform_config.go#L832)).
Guided start imports this existing configuration after verifying test credentials,
including after a stop. Manual first-time Terraform provisioning still creates it.
Enabled project APIs, any historical demo-token secret, local configuration and
private state backups remain. Retained secret versions can incur charges.
A later `start` provisions resources again and
automatically updates phone and worker configuration with the current service URL.
Omitting `start`/`stop` retains the original `start` behavior.

Cloud Tasks can block reuse of a deleted queue name for up to three days. The
guided script automatically chooses a fresh queue ID for a new deployment or
restart after stop, and keeps the ID of an existing Terraform-managed queue.
Manual Terraform users can set `annotation_queue_name` to a fresh ID themselves.
Firestore also temporarily reserves deleted database IDs. Guided start uses a
fresh named database after teardown and keeps an existing database's ID on
subsequent starts. The release automatically receives this ID; no client changes
are needed. Manual Terraform provisioning defaults to `(default)` and can select
`firestore_database_id` explicitly.

Run from the repository root:

```bash
uv sync --project backend --extra dev --locked
backend/.venv/bin/python scripts/deploy-gcp.py build
python3 scripts/terraform-gcp.py init
python3 scripts/terraform-gcp.py validate
python3 scripts/terraform-gcp.py plan -out=phone.tfplan
python3 scripts/terraform-gcp.py apply phone.tfplan
```

Review the saved plan displayed by apply, then type `apply`. Plan/apply require
local `home-safety-backend:dev` labelled with a hash of current Dockerfile, Docker
ignore rules, locked dependencies and application sources. Missing/stale images
stop with the exact build command. No remote image is needed before Terraform
creates Artifact Registry. Backend changes require a rebuild. Credentials, local
`.env`, tests, Terraform state and mobile assets never enter the image.

The wrapper keeps state/plans private and creates backups in the ignored
`.tools/terraform-state-backups/`, including after failed applies. Keep another
private off-machine backup. Never commit state/plans. An older state may own the
demo-token secret: run `python3 scripts/terraform-gcp.py detach-demo-token`
before migrating. This backs up state and leaves the live secret untouched. Never
approve a plan deleting that secret. Preserve/import existing Firestore/GCS rather than replacing live
storage to fix a state mismatch.

## Secrets and first release

Configure `MUSE_API_KEY` and `MUSE_MAIN_MODEL` in root `.env`:

```bash
backend/.venv/bin/python scripts/deploy-gcp.py secrets --provider muse
backend/.venv/bin/python scripts/deploy-gcp.py release --provider muse --model YOUR_MUSE_MAIN_MODEL
```

Register the Firebase JS client app in the same project and configure the public
client values as described in [authentication setup](../docs/authentication.md).
Run `deploy-gcp.py configure-auth` after provisioning to enable enumeration
protection and the required password policy. Configure browser email templates and
action domains in Firebase. A current verified test-user token must be supplied in
`HOME_SAFETY_SMOKE_ID_TOKEN` to release, verify, rollback or generate phone settings.
It stays in operator memory and is never written into client configuration.

Model-key uploads use numbered Secret Manager versions with values on stdin;
there is no shared demo-token authentication. Preserve model-key versions needed
for rollback. Before the first release, provision Scheduler recovery using the
canonical service origin; the guided script resolves it from the project number.
Account deletion needs this sweep even when segmentation is disabled.

Releases build unique immutable tags and deploy by
digest. Existing services receive a tagged candidate without traffic; verification
precedes promotion. Candidate failures preserve existing traffic. Post-promotion
verification failure restores the previous revision. A first release has initial
traffic before verification because there is no prior revision; inspect logs and
release a correction on failure. Use `--image=REPOSITORY/backend@sha256:DIGEST` to
reuse a previously pushed image from this repository.

## Durable highlights

The guided script configures this automatically. For manual deployment, get the
current service URL:

```bash
backend/.venv/bin/python scripts/deploy-gcp.py service-url
```

Set that URL in private tfvars:

```hcl
annotation_worker_url = "https://YOUR_SERVICE.run.app"
```

Apply the recovery configuration before enabling segmentation:

```bash
python3 scripts/terraform-gcp.py plan -out=highlights.tfplan
python3 scripts/terraform-gcp.py apply highlights.tfplan
backend/.venv/bin/python scripts/deploy-gcp.py release --provider muse --model YOUR_MUSE_MAIN_MODEL --segmentation-model sam-3.1
```

The authenticated once-per-minute Scheduler sweep recovers persisted dispatch intent.
Cloud Tasks uses Google OIDC to deliver independent finding attempts. Firebase user
tokens cannot invoke internal worker routes. Firestore fences started attempts;
expiry fails an attempt and only explicit user retry starts new model work. Queue
concurrency 24 and Cloud Run concurrency 8 with 2 instances admit 12 overlapping
attempts; cold starts/load may queue work (ADRs 0002/0003). Terraform supplies the
queue, stable worker URL and service-account identity to the release workflow.

## Connect Expo Go

```bash
backend/.venv/bin/python scripts/deploy-gcp.py phone-env
source scripts/frontend-env.sh
cd mobile
npm run start:tunnel -- --go --clear
```

`phone-env` verifies the serving API using the operator's test-user token, then
writes API mode, the current service URL and Firebase project ID to the root `.env`.
Set the public Firebase app key/app ID/auth domain separately. It removes legacy
demo-token entries. All npm launch commands load only root `EXPO_PUBLIC_` entries.
Native secure persistence and Expo Go compatibility require device verification;
see [authentication setup](../docs/authentication.md) before release.

Explore assessments, text/photo follow-ups, user reviews, highlights, checklist
updates, restart persistence and deletion. Model requests consume quota; these
journeys are not deployment gates. Record observations in `docs/demo.md` without
claiming detection accuracy from a small demo set.

## Verification and operations

```bash
backend/.venv/bin/python scripts/deploy-gcp.py status
backend/.venv/bin/python scripts/deploy-gcp.py verify
backend/.venv/bin/python scripts/deploy-gcp.py rollback PREVIOUS_REVISION
```

The verifier checks public liveness, missing/invalid user-token rejection, disabled
docs and protected private storage CRUD using a verified test account. Its fixture
is removed without a model call. Cross-account isolation is covered with local
Auth/storage emulators; repeat with two cloud test users before release.

Rollback rejects legacy demo-auth revisions and verifies the target with a current
Firebase token before restoring traffic; it does not roll back data. Run one release/rollback at a time and retain
needed revisions/images/versions. Scale-to-zero retains data/photos. Registry,
storage and secrets can incur ongoing charges.
No automatic teardown or hard spending cap is configured.

## Explicit teardown

Only when the owner intends to remove persistent test data:

```bash
python3 scripts/deploy.py stop
```

The wrapper warns about assessment/photo deletion, creates/displays a destroy plan,
requires typing `destroy`, removes Cloud Run using the plan's project and region,
and applies the plan only after successful service removal. It does not need
release outputs. Before deleting a whole Firestore database, it backs up state and
detaches that database's field configurations to avoid unnecessary index resets.
It regenerates the plan after this state change and rejects newly introduced
deletions. The database deletion removes the fields and data together.
No current image is required.
Firestore deletion protection is disabled and bucket destruction includes objects.
Any historical unmanaged demo-token secret remains unused and can be retired separately.

## Local checks

```bash
backend/.venv/bin/python -m pytest backend/tests -m 'not live' -q
backend/.venv/bin/ruff check --config backend/pyproject.toml backend scripts
python3 scripts/terraform-gcp.py fmt -check
python3 scripts/terraform-gcp.py validate
source scripts/frontend-env.sh
npm --prefix mobile run typecheck
npm --prefix mobile test
```

Sources: [Cloud Run with Cloud Tasks](https://docs.cloud.google.com/run/docs/triggering/using-tasks),
[Expo environment variables](https://docs.expo.dev/guides/environment-variables/).
