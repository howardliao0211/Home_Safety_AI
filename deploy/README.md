# GCP Android phone test

The owner runs Expo Go on Android, the development computer runs the Expo tunnel,
and FastAPI runs in project `home-safety-ai`, region `us-central1`. Keep resources
and data until explicit destroy. No automatic teardown is installed. Readiness
requires cloud auth/storage/TLS checks; real Muse and phone journeys are exploratory.

## Ownership and prerequisites

| Component | Owner |
| --- | --- |
| Infrastructure lifecycle, local image gate, private local state/backups | `scripts/terraform-gcp.py` |
| APIs, Artifact Registry, Firestore/GCS, service accounts/IAM, Tasks/Scheduler, DNS, global load balancer/IP/TLS | Terraform configuration |
| Build/push, secret versions, Cloud Run revisions/traffic, verification, rollback, service deletion | `scripts/deploy-gcp.py` |
| Domain registration and persistent demo-token secret | Outside phone-test Terraform state |

Install Docker, gcloud, Terraform >=1.14 and <2, uv/Python >=3.10 and pinned Node.
Sign in using `gcloud auth login`. The provisioning account needs API, storage,
registry, service account/IAM, secrets, Tasks/Scheduler, Compute/DNS and Firestore
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
and a 300-second timeout. Invocation is public; FastAPI requires the demo bearer
token and scopes records/photos by per-installation device ID. Production API docs
are disabled. Model credentials stay backend-only. The phone uses a stable custom
HTTPS hostname through a global external Application Load Balancer with regional
serverless NEG, reserved global IPv4 and Google-managed TLS. Cloud Run's `run.app`
URL remains available for tagged-revision verification.

## Build and provision

Run from the repository root:

```bash
uv sync --project backend --extra dev --locked
backend/.venv/bin/python scripts/deploy-gcp.py build
python3 scripts/terraform-gcp.py init
python3 scripts/terraform-gcp.py validate
python3 scripts/terraform-gcp.py plan -out=phone.tfplan
python3 scripts/terraform-gcp.py apply phone.tfplan
```

Review the saved plan displayed by apply, then type `apply`. Init/plan/apply require
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

Every phone-test release explicitly selects Muse and its model. Groq is still the
legacy CLI default for development. The secrets command uploads a numbered Muse-key
version and initializes the external demo-token secret once, using configured
`DEMO_BEARER_TOKEN` or generating a random token. Later calls reuse its enabled
version and restore runtime secret access. Bytes travel through stdin pipes, never
arguments, logs, images or Terraform state. Set `demo_token_initialized = true` in
private `deploy/terraform/terraform.tfvars` after initialization so Terraform manages
its runtime accessor binding on later applies. The secret itself survives destroy.

Only rotate deliberately with `secrets --provider muse --rotate-demo-token`.
Revisions pin numbered versions; retain enabled versions needed for rollback. If
the external secret itself is deleted, create a replacement token and update root
`.env`. The shared token is client-visible; model keys are never public variables.

The initial release runs without segmentation and can use `run.app` while domain
registration/TLS completes. Releases build unique immutable tags and deploy by
digest. Existing services receive a tagged candidate without traffic; verification
precedes promotion. Candidate failures preserve existing traffic. Post-promotion
verification failure restores the previous revision. A first release has initial
traffic before verification because there is no prior revision; inspect logs and
release a correction on failure. Use `--image=REPOSITORY/backend@sha256:DIGEST` to
reuse a previously pushed image from this repository.

## Domain and TLS

After bootstrap enables Cloud Domains, check live availability and annual price:

```bash
gcloud domains registrations get-register-parameters YOUR_DOMAIN --project=home-safety-ai
```

Confirm the exact domain and price with the owner before registering. Registration
stays outside Terraform state. Supply registrant contact details privately and
complete contact verification/terms acceptance; do not commit personal information.
Cloud Domains defaults to annual automatic renewal, managed independently of
infrastructure teardown.

Set `domain_name = "YOUR_DOMAIN"` in private Terraform tfvars, then plan/apply through
the wrapper. Empty is the bootstrap default. Enabling it creates the Cloud DNS zone,
API A record, reserved IP, global load balancer and managed certificate. Read
`python3 scripts/terraform-gcp.py output domain_name_servers` and use those Cloud
DNS name servers for Cloud Domains registration/delegation. The zone can be created
before registration to obtain these values. Wait for DNS propagation and managed
certificate ACTIVE status, then run `deploy-gcp.py verify` with the backend Python.

The hostname survives Cloud Run recreation while DNS/load-balancer resources remain.
Destroy may remove the zone, record, IP, load balancer and certificate. Recreating
an IP reservation can allocate a different address; restore the A record to the
current IP, and update Cloud Domains delegation if recreated name servers differ.
Domain registration and the demo-token secret remain outside this lifecycle.

## Durable highlights

After the initial backend and custom hostname work, set private tfvars:

```hcl
annotation_worker_url = "https://api.YOUR_DOMAIN"
demo_token_initialized = true
```

Apply the recovery configuration before enabling segmentation:

```bash
python3 scripts/terraform-gcp.py plan -out=highlights.tfplan
python3 scripts/terraform-gcp.py apply highlights.tfplan
backend/.venv/bin/python scripts/deploy-gcp.py release --provider muse --model YOUR_MUSE_MAIN_MODEL --segmentation-model sam-3.1
```

The authenticated once-per-minute Scheduler sweep recovers persisted dispatch intent.
Cloud Tasks uses Google OIDC to deliver independent finding attempts. The shared demo
token cannot invoke internal worker routes. Firestore fences started attempts;
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

`phone-env` verifies the custom endpoint, then privately updates root `.env` with
`EXPO_PUBLIC_DATA_SOURCE=api`, `EXPO_PUBLIC_API_URL=https://api.<domain>` and
`EXPO_PUBLIC_DEMO_TOKEN` matching the serving revision's pinned token. It also aligns
`DEMO_BEARER_TOKEN` for local use, retaining other settings. Model keys stay backend-only.
All npm Expo launch commands load only root `EXPO_PUBLIC_` entries. Inherited process
variables take precedence; `mobile/.env` is unnecessary and ignored. Restart Expo
after changes. Scan the QR code using Android Expo Go compatible with SDK 57.
Keep the development computer/tunnel running for repeated phone tests.

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

The verifier rejects missing/invalid tokens, checks authenticated health and disabled
docs, then creates/reads/retrieves/scopes/deletes a tiny Firestore/GCS assessment/photo
fixture without a model request. Another device cannot read the assessment or photo.
Cleanup runs on failure; if cleanup fails, fixture identifiers allow explicit deletion
after fixing storage access. With a configured domain, verification checks both
`run.app` and custom HTTPS: public DNS and the Cloud DNS A record must match the
reserved IP, the managed certificate must be ACTIVE and TLS must validate. Pending
DNS/TLS fails readiness explicitly.

Rollback verifies the target with its original pinned token version before restoring
traffic; it does not roll back data. Run one release/rollback at a time and retain
needed revisions/images/versions. Scale-to-zero retains data/photos. Registry,
storage, secrets, DNS, reserved IP and load balancing can incur ongoing charges.
No automatic teardown or hard spending cap is configured.

## Explicit teardown

Only when the owner intends to remove persistent test data:

```bash
python3 scripts/terraform-gcp.py destroy
```

The wrapper warns about assessment/photo deletion, creates/displays a destroy plan,
requires typing `destroy`, invokes `deploy-gcp.py delete-service` first and applies
the plan only after successful service removal. No current image is required.
Firestore deletion protection is disabled and bucket destruction includes objects.
Domain registration and the external demo-token secret remain.

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

Sources: [Google serverless load balancing](https://docs.cloud.google.com/load-balancing/docs/https/setup-global-ext-https-serverless),
[Cloud Domains registration](https://docs.cloud.google.com/domains/docs/register-domain),
[Expo environment variables](https://docs.expo.dev/guides/environment-variables/).
