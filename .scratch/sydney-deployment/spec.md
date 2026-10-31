# Rebuild the backend deployment in Sydney

## Purpose and agreed scope

Deploy the Home Safety AI backend and its regional dependencies in GCP Sydney
(`australia-southeast1`) instead of `us-central1`, bringing the application
infrastructure closer to the Australian phone demo. This is a fresh deployment,
not a data migration.

The user confirmed:

1. Existing assessment, finding, photo, chat and other regional application data
   may be discarded. No migration or historical-data compatibility is required.
2. Before/after latency measurements and performance targets are excluded.
3. Use the existing `home-safety-ai` project. Move all regional resources, update
   release tooling and mobile API configuration, and keep project-wide login,
   secrets, the model provider and scaling settings.
4. A destructive regional rebuild, downtime and retirement of the old US
   deployment are acceptable. Include functional deployment checks.

This task creates the specification only. Implementation and cloud operations
are subsequent work; this document does not report a completed deployment.

## Current implementation

- `deploy/terraform/variables.tf` defaults `region` to `us-central1`. It drives
  Firestore, the photos bucket, Artifact Registry, Cloud Tasks and Cloud Scheduler.
- `deploy/terraform/outputs.tf` exports the region and regional repository URL.
  Cloud Run services, revisions and traffic belong to `scripts/deploy-gcp.py`,
  rather than Terraform.
- `scripts/deploy.py` orchestrates Terraform and releases. Its generated, ignored
  `deploy/terraform/deploy.tfvars.json` is loaded after ordinary inputs, so an old
  explicit region can override an updated Terraform default.
- Bootstrap retains existing database/queue IDs and a nonempty worker URL.
  Finish discovers the Cloud Run URL and refreshes worker configuration. Reusing
  the old worker URL during a regional rebuild can target the US service.
- The worker origin controls task delivery, OIDC audiences and Scheduler recovery.
  Recovery also supports account deletion, so it remains required.
- The normal stop path destroys Terraform-managed dependencies, including model
  secret resources. It is not a sufficient unchanged procedure for a rebuild
  that must retain the existing project-wide secrets.

## Target deployment

| Component | Required outcome |
| --- | --- |
| Cloud Run API and internal workers | Release `home-safety-demo` in `australia-southeast1`; no serving US predecessor remains |
| Firestore | Fresh Standard edition Native database in `australia-southeast1`, with required indexes and empty application data |
| Private photo and mask storage | Regional Sydney bucket with existing backend-only access, versioning disabled and soft delete disabled |
| Artifact Registry | Sydney `home-safety` repository; releases use its regional image URL |
| Cloud Tasks | Sydney queue; deliveries use the Sydney worker origin and matching OIDC audience |
| Cloud Scheduler | Sydney recovery job; target and OIDC audience use the Sydney origin |
| Identity Platform / Firebase | Existing project and account configuration remain usable; no account deletion or recreation is required |
| Secret Manager | Retain existing model secret resources and numbered versions; preserve backend access |
| Mobile | The public API setting points at the verified Sydney Cloud Run origin |

Keep the current backend service account and project-wide IAM unless a regional
dependency requires an IAM reference update. Preserve current runtime resources,
concurrency, instance limits, timeout, authentication and provider/model choices.
Do not add minimum instances, change models, or redesign application workflows.

## Terraform and deployment tooling requirements

### Region configuration

Set the Terraform region default and example configuration to
`australia-southeast1`. Continue deriving every regional resource and release
setting from the selected region; do not scatter Sydney string literals across
the release implementation. Retain support for explicit alternative regions.

Provide a documented, explicit region selection for the guided deployment and
persist it in its generated variables. Show the effective project and region
before mutation. Define input precedence so stale generated US variables cannot
silently override an explicitly selected Sydney target. An ordinary repeated
start must retain resources in the same region; changing a default must not
silently trigger destruction of an existing deployment.

### Controlled destructive rebuild

Provide an explicit procedure or command for rebuilding regional resources while
retaining shared project resources and secrets. Do not instruct the operator to
blindly change `region` and apply, or run the unchanged full stop path.

The procedure must:

1. Capture the source project, source region and service identity before changing
   target inputs. Use existing private Terraform state and reviewed plans; retain
   the current plan/apply confirmation gates and state-backup conventions.
2. Stop US task dispatch and recovery, then remove the US Cloud Run service before
   removing its storage and other dependencies. In-flight requests/tasks may be
   abandoned because their application data is being discarded.
3. Delete old regional resources and their application data through a reviewed
   Terraform workflow, retaining ownership of shared resources. Do not destroy
   Identity Platform accounts, existing model secrets/versions, or the project.
4. Provision fresh Sydney resources. Allocate fresh Firestore and queue IDs when
   required to avoid deleted-name reuse delays. Handle bucket naming/recreation
   explicitly; a failed name reuse must leave a clear, resumable operation rather
   than switching silently to a US resource.
5. Clear the old worker origin for the target bootstrap. Any provisional origin
   must be derived from the Sydney service identity. Reconcile it against the
   actual Cloud Run URL, and update tasks, Scheduler and OIDC audiences together.
   No Sydney deployment stage may deliver work to the former US service.
6. Build/push to the Sydney registry, release in Sydney, finish worker setup and
   verify the resulting service. Configure the phone only after verifying it.
7. Confirm the former US Cloud Run service, queue and recovery job are gone and
   the regional Terraform state describes the Sydney resources.

Keep source-region cleanup separate from target-region release operations:
changing the active region must not cause teardown to look for the old service
in Sydney. Do not leave unmanaged regional resources or solve this by deleting
Terraform state. Preserve the existing split between Terraform infrastructure
ownership and the release CLI's Cloud Run ownership.

Failures must report the affected phase and how to resume. Never automatically
destroy the new deployment on a release/verification failure. Once source data
has been deleted there is no data rollback; recovery is finishing or retrying the
fresh deployment. Revision rollback remains scoped to a service within its
configured region and must not claim to restore the US deployment.

### Mobile connection and stale state

Use the existing `phone-env` flow to save the verified Sydney HTTPS origin in
root `EXPO_PUBLIC_API_URL`, preserving current Firebase client configuration.
Document restarting Expo with a cleared bundler cache so the phone picks it up.

The phone must open against the new empty backend. Existing local references to
discarded assessments need not be migrated. Include an operator step to clear
stale local assessment state using the app's existing reset/sign-out facilities
or a clean installation as needed, then sign in with the existing account.
Do not add a client data migration or automatically import old local data.

## Documentation and architectural consistency

Update regional guidance in `CONTEXT.md`, root `README.md`, `deploy/README.md`
and Terraform examples during implementation. Document fresh Sydney setup,
the destructive US-to-Sydney rebuild, explicit region precedence, failure resume
steps and phone reconnection. Keep any credentials/state/generated inputs private.

This spec supersedes the US regional deployment details in
`.scratch/gcp-phone-test/spec.md`; its obsolete demo-token/device authentication
and proposed domain/load-balancer setup are not requirements for this work.
Continue current verified-account authentication and generated Cloud Run HTTPS
origins.

No conflict with ADRs 0001–0003 was identified. Keep backend-owned Firestore/GCS,
retryable cross-store deletion and durable independent highlight execution.
The region in `CONTEXT.md` changes under this approved plan; no storage or worker
architecture replacement is proposed.

## Acceptance criteria and verification

1. Terraform defaults/examples select Sydney. Terraform formatting and validation
   pass. A reviewed target plan places all listed regional resources in Sydney
   and retains existing global login and secrets.
2. Focused deployment tests verify explicit region precedence over stale generated
   inputs, same-region restart behavior, source-region teardown after selecting
   Sydney, preservation of shared secrets/login, fresh IDs after teardown and
   failure/resume behavior. Extend `scripts/tests/test_deploy.py` and
   `scripts/tests/test_deploy_lifecycle.py` as appropriate.
3. Tests capture release/build commands and worker configuration: Sydney registry,
   Cloud Run region, task queue, recovery target and OIDC audience must agree.
   Bootstrap/finish must not reuse a saved US worker URL for the Sydney rebuild.
4. After the subsequent deployment, inspect actual resource locations and serving
   origin. Confirm removal of the old regional deployment and successful login
   using an existing verified account. The account begins with empty history.
5. On a physical phone, create an assessment, load its saved photo/findings, send
   a finding-chat question, update checklist status and reopen the assessment
   after restart. Check highlights and authenticated worker delivery/recovery,
   including the existing account-deletion recovery path using a disposable
   test account. Confirm assessment/photo deletion remains functional.
6. Record functional results and any unavailable cloud/device checks. Do not
   claim faster responses from a region change alone; no timing benchmark,
   percentage improvement or latency service-level target is required.

## External constraints and references

- [Cloud Run locations](https://docs.cloud.google.com/run/docs/locations)
  lists Sydney as `australia-southeast1`.
- [Firestore locations](https://firebase.google.com/docs/firestore/locations)
  states that a provisioned database's location cannot be changed; this plan
  creates a fresh database rather than moving an existing one.
- [Cloud Run environment setup](https://docs.cloud.google.com/run/docs/setup)
  recommends considering both users and dependent service locations.

The external Muse/SAM and Groq endpoints and global identity services remain as
configured. Regional application hosting does not establish Australian model
processing or guarantee that model generation becomes faster. Optimizing model
latency, adding tracing/benchmarks and changing provider residency are outside
this approved scope.
