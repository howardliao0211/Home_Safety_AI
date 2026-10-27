# Cloud Run backend deployment

Deploy the FastAPI backend to Cloud Run in `us-central1`, project
`home-safety-ai`. The Expo app remains the client. Firestore/GCS hold durable
assessment data and photos; Cloud Run containers hold no durable app state.

The Docker image and workflows are implemented and verified locally. No Cloud
Run service or new cloud resources have been provisioned by this change. The
previous Compute Engine demo was destroyed on 2026-10-27; its reserved IP is no
longer ours. This workflow supersedes the VM/nginx/Certbot deployment.

## Ownership and defaults

| Component | Managed by |
| --- | --- |
| Required APIs, Artifact Registry, runtime service account, Firestore/GCS, secret containers and runtime IAM | `deploy/terraform/` |
| Image builds/pushes, Cloud Run service configuration, revisions, public invocation and traffic | `scripts/deploy-gcp.py` |
| Secret values and numbered versions | Release CLI `secrets` command, outside Terraform |
| Model credentials | Secret Manager; referenced by numbered version on each revision |

Cloud Run starts with **1 CPU, 2 GiB RAM, concurrency 2, minimum 0, maximum 2
instances**, request-based CPU allocation, and a **300-second request timeout**.
These are starting settings, not measured capacity guarantees. Google supplies
the HTTPS `run.app` URL; nginx, a public VM port, an IP certificate, and SSH are
unnecessary. The container runs as UID/GID 10001 and listens on `0.0.0.0:$PORT`.

Cloud Run invocation is public so the mobile client does not need a Google IAM
identity token. FastAPI requires `Authorization: Bearer <demo token>` on API
routes, including `/healthz`, and scopes records/photos by `X-Device-ID`.
`/docs`, `/redoc`, `/openapi.json` and Swagger's OAuth redirect are disabled in
production. Cloud Run uses its default TCP startup probe; HTTP verification
supplies the token without putting it into probe configuration.

## Local prerequisites and image check

Install Docker Engine, gcloud, Terraform >=1.14 and <2, and uv/Python 3.10+.
Run all commands below from the repository root:

```bash
uv sync --project backend --extra dev --locked
uv run --project backend python scripts/deploy-gcp.py build
```

This builds `home-safety-backend:dev` for Linux AMD64 without cloud access.
`backend/Dockerfile` pins the Python/uv base images by digest and installs runtime
packages from `backend/uv.lock`. The build context is only `backend/` and its
`.dockerignore` allows application code and locked package metadata. Local `.env`,
credentials, tests, Terraform state, development tools, and mobile assets do not
enter the image. The image defaults to production; testing it with emulators
requires an explicit `ENVIRONMENT=local` override.

Docker's authenticated local health check runs `python -m app.healthcheck`.
Cloud Run uses its own startup probe rather than Docker's HEALTHCHECK instruction.

## 1. Provision shared infrastructure

Sign in with the account that can manage the existing billed project:

```bash
gcloud auth login
gcloud auth list
# Copy only if you do not already have a tfvars file.
cp deploy/terraform/terraform.tfvars.example deploy/terraform/terraform.tfvars
terraform -chdir=deploy/terraform init
terraform -chdir=deploy/terraform validate
python3 scripts/terraform-gcp.py plan -out=cloud-run.tfplan
python3 scripts/terraform-gcp.py apply cloud-run.tfplan
```

Review the saved plan before applying. Existing VM-era tfvars must remove
`certificate_email`, `zone`, and `machine_type`; the new inputs are `project_id`
and `region`. This configuration preserves the Terraform resource addresses
and names for Firestore, GCS, and the dedicated service account. Restoring an
older state with live VM resources will propose deleting the VM/network/IP;
inspect that plan before applying. Do not replace existing storage to resolve a
state mismatch. Import matching existing storage or restore its state instead.

The provisioning account needs permissions to enable APIs, manage Artifact
Registry, Firestore, Storage, Secret Manager and service accounts, and grant the
runtime IAM bindings. The runtime identity receives `roles/datastore.user`,
`roles/storage.objectUser` on the photo bucket only, and
`roles/secretmanager.secretAccessor` on the two model/demo secrets only. Cloud
Run captures stdout/stderr without an app logging-writer role. Same-project image
pulls use Cloud Run's Google-managed service agent.

The release operator additionally needs Artifact Registry upload access, Cloud
Run service/traffic and public-invoker policy management, service-account usage,
and access to add/read the selected Secret Manager versions. Terraform does not
grant the operator roles to itself. A project owner may already have them.

The existing Terraform wrapper selects the active gcloud account and passes a
short-lived access token through the child environment. Use `--account=EMAIL`
before its command to override that account. State and state backups remain
local and ignored; keep a private off-machine backup. The release script reads
only the non-secret `deployment_config` Terraform output. It never provisions
infrastructure or runs Terraform apply.

## 2. Initialize secrets

Keep your working `GROQ_API_KEY` and `GROQ_MODEL` in the root `.env`:

```bash
uv run --project backend python scripts/deploy-gcp.py secrets
```

The command adds a numbered Groq-key version. On first use, it initializes the
demo token from `DEMO_BEARER_TOKEN` if provided, otherwise generates a random
token. Subsequent calls reuse the existing demo token. Secret bytes are sent via
stdin pipes, not command arguments, files, image layers or Terraform state.
Secret containers and access policies are provisioned by Terraform; the script
only adds secret versions. It does not print secret values or change `.env`.

To rotate the Groq key, update `.env`, run `secrets`, then release again.
To deliberately rotate the demo token too:

```bash
uv run --project backend python scripts/deploy-gcp.py secrets --rotate-demo-token
```

A release resolves enabled versions and pins their actual version numbers.
Existing revisions keep their original versions. Keep rollback revisions'
versions enabled. The mobile client needs the demo token used by the serving
revision; retrieve that specific version in your own Secret Manager console or
terminal. Changing the token requires updating the client configuration.

The local `.env` emulator/project settings are never copied into production.
Production gets storage/project settings from Terraform outputs and key/token
values from Secret Manager. The Google SDKs use the attached Cloud Run service
identity through Application Default Credentials; no downloaded GCP key is needed.

## 3. Release and verify

```bash
uv run --project backend python scripts/deploy-gcp.py release
uv run --project backend python scripts/deploy-gcp.py status
uv run --project backend python scripts/deploy-gcp.py verify
```

Pass `--account=EMAIL` before the subcommand when selecting a different operator.
`release` reads the model ID from `GROQ_MODEL` in the process environment or root
`.env`; override with `release --model=MODEL_ID` if needed. It builds a uniquely
tagged image, pushes it to Artifact Registry, resolves its immutable digest,
then deploys by that digest. Artifact Registry tags are immutable. Temporary
Docker login configuration is removed after pushing. Build/push time does not
consume Cloud Run instances.

When a service already exists, the new revision receives a tagged HTTPS URL and
no service traffic. Verification checks:

- Missing/wrong tokens are rejected and authenticated health succeeds.
- Production API documentation routes return 404.
- A tiny generated photo/assessment can be created, read, retrieved through the
  private-photo API, scoped to its device, and deleted using real Firestore/GCS.

These checks do not call the model or consume Groq quota. Only after verification
passes does the script route 100% of service traffic to the candidate. It then
checks the service URL; if that check fails, it restores the prior revision.
Failed candidate verification leaves prior service traffic unchanged. Failed
candidates may retain their tagged URLs, still protected by the app's token.
On the **first release**, Cloud Run creates the service and initial traffic before
verification because there is no previous revision. A first-release failure is
reported; inspect its logs/configuration, then release a correction.

A deployment fixture is deleted in verification's cleanup step even when later
checks fail. If storage deletion itself fails, finish removing that fixture after
fixing permissions. Run one release/rollback at a time; this script deliberately
manages a single revision serving 100% of traffic, rather than traffic splits.

To reuse an already-pushed image:

```bash
uv run --project backend python scripts/deploy-gcp.py release   --image=us-central1-docker.pkg.dev/home-safety-ai/home-safety/backend@sha256:IMAGE_DIGEST
```

The image must belong to the provisioned backend repository. Image tags and
Cloud Run revision names are separate: releases report the new revision and
previous revision to make rollback explicit.

## Rollback and operations

```bash
uv run --project backend python scripts/deploy-gcp.py rollback PREVIOUS_REVISION
uv run --project backend python scripts/deploy-gcp.py verify
gcloud run services logs read home-safety-demo --project=home-safety-ai --region=us-central1 --limit=50
```

Rollback checks that the target revision belongs to this service, gets the demo
token version pinned on that revision, assigns it a verification URL, and verifies
it before restoring traffic. It restores the revision's image and model/secret
configuration; it does not roll back Firestore data. Old clients need the token
corresponding to whichever revision serves traffic. Do not delete retained images,
revisions, or secret versions while they are needed for rollback.

Cold starts are expected with minimum 0. To keep one instance warm during a
scheduled demo, then return to the normal default:

```bash
gcloud run services update home-safety-demo --project=home-safety-ai --region=us-central1 --min=1
gcloud run services update home-safety-demo --project=home-safety-ai --region=us-central1 --min=0
```

A new scripted release reapplies minimum 0. Scale-to-zero avoids idle request-based
compute charges, but storage, Artifact Registry, Secret Manager and network usage
can still incur charges. Model waiting time is active request time on Cloud Run;
Groq quotas and costs remain independent. There is no automatic model retry.

## Removal

Cloud Run service lifecycle belongs to the release workflow, outside Terraform.
Delete it explicitly before removing its supporting resources:

```bash
gcloud run services delete home-safety-demo --project=home-safety-ai --region=us-central1
python3 scripts/terraform-gcp.py plan -destroy -out=destroy.tfplan
python3 scripts/terraform-gcp.py apply destroy.tfplan
```

Inspect the destroy plan. Existing user-approved Firestore/GCS deletion guards
remain removed: full teardown can delete the database and photo objects. Secret
container removal also removes its stored versions. Terraform state does not
contain the versions' values, but state backups remain private.

## Local verification

```bash
uv run --project backend pytest backend/tests -m 'not live' -q
uv run --project backend ruff check --config backend/pyproject.toml backend scripts/deploy-gcp.py
terraform -chdir=deploy/terraform fmt -check
terraform -chdir=deploy/terraform validate
```

Automated checks cover production auth/docs behavior, the storage verifier,
secret stdin handling, candidate failure without traffic promotion, post-promotion
traffic restoration, and rollback using the revision's pinned secret version.
A local container smoke check also verifies custom PORT binding, non-root runtime,
health and storage CRUD with local emulators. Live GCP rollout/IAM checks require
provisioning and remain separate from local verification.

References: [Cloud Run container contract](https://docs.cloud.google.com/run/docs/container-contract),
[secret versions](https://docs.cloud.google.com/run/docs/configuring/services/secrets),
[deployment flags](https://docs.cloud.google.com/sdk/gcloud/reference/run/deploy),
[billing](https://docs.cloud.google.com/run/docs/configuring/billing-settings).
