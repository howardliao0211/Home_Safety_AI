# GCP phone test deployment

## Goal

Prepare and run a private Android phone test of Home Safety AI using Expo Go and a GCP-hosted backend. Keep the environment available for repeated tests until the operator explicitly destroys it.

## Scope

- Android physical phone using Expo Go; the development computer runs the Expo server/tunnel.
- One trusted tester: the owner. Use the existing shared demo bearer token and per-installation device ID.
- GCP project `home-safety-ai`, region `us-central1`, Cloud Run API, Firestore Standard Native mode, private GCS photo storage, Secret Manager, Cloud Tasks, and Cloud Scheduler for durable highlight attempts and recovery.
- Muse is the cloud model provider. Keep model credentials backend-only in Secret Manager.
- Include assessment, follow-up, review, checklist persistence, finding highlights, and deletion capabilities for phone exploration. Deployment completion does not depend on exercising every capability on the phone.
- Register an available domain through Cloud Domains, host its DNS zone in Cloud DNS,
  and expose the API at `https://api.<domain>` through a global external Application
  Load Balancer with a reserved static IP and Google-managed TLS. Select the exact
  domain after checking availability and price.
- The hostname remains stable across Cloud Run service recreation while the domain,
  DNS record, and load balancer are retained. Terraform destroy may remove the DNS
  zone and load balancer; no deletion protection is required. Recreating them requires
  restoring the DNS record to the reserved IP. Domain registration is outside the
  phone-test Terraform state.
- Keep the demo bearer token stable across backend releases and phone-test Terraform
  destroy/recreate by managing its Secret Manager secret outside the phone-test state.
  Initialize it once and reuse its active version; rotate only by explicit operator
  action. If the secret itself is deleted, a replacement token is required and the root
  `.env` must be updated.
- Use the existing starting Cloud Run settings: 1 CPU, 2 GiB RAM, concurrency 8, minimum 0 and maximum 2 instances, and a 300-second request timeout.

## Provisioning and release ownership

All Terraform lifecycle operations must be run through `scripts/terraform-gcp.py`, including `init`, `plan`, `apply`, and `destroy`. The wrapper owns infrastructure lifecycle and checks whether the required current local backend image exists before `init`, `plan`, and `apply`. If the image is missing or stale, stop and print the exact `scripts/deploy-gcp.py build` command. Destroy must remain available without an image.

Terraform owns enabled APIs, Artifact Registry, service accounts and IAM, Firestore,
GCS, Cloud Tasks, Cloud Scheduler, the Cloud DNS zone/records, reserved load-balancer
IP, load balancer, and TLS certificate. The demo-token Secret Manager secret is managed
outside this Terraform state. `scripts/deploy-gcp.py` owns image build/push,
model-secret version upload, Cloud Run releases, health/storage verification, traffic
promotion, status, and rollback; ordinary releases reuse the existing demo-token
version. The Terraform wrapper may inspect image/release state and tell the operator
which release command is needed; it must not silently take over the release workflow.

Terraform creates Artifact Registry, so the first deployment has a local build before infrastructure provisioning and an image push/release after the registry exists:

1. Build the backend image from the current source with `scripts/deploy-gcp.py build`.
2. Initialize, review a plan, and apply infrastructure through `scripts/terraform-gcp.py`.
3. Register the domain with Cloud Domains; provision its Cloud DNS zone, API record,
   load balancer, reserved static IP, and managed TLS certificate.
4. Add the Muse API key and initialize/reuse the demo token with
   `scripts/deploy-gcp.py secrets --provider muse`.
5. Release the initial backend without segmentation, explicitly selecting Muse and its model.
6. Set Terraform's `annotation_worker_url` to `https://api.<domain>` and reapply through
   `scripts/terraform-gcp.py` to configure scheduled recovery.
7. Release the backend with Muse highlighting enabled (`--provider muse`, `--model`, and `--segmentation-model sam-3.1`).
8. Configure the root `.env` with `EXPO_PUBLIC_DATA_SOURCE=api`,
   `EXPO_PUBLIC_API_URL=https://api.<domain>`, and the same demo bearer token as
   `EXPO_PUBLIC_DEMO_TOKEN`. Expo launch commands must load this root `.env`; no separate
   `mobile/.env` is required. Restart Expo after changing these values and connect the
   phone using the Expo tunnel.

Release commands must explicitly select Muse and a Muse model. Existing CLI defaults select Groq, so relying on defaults is not acceptable for this deployment.

## Terraform wrapper behavior

- Provide wrapper commands for `init`, `plan`, `apply`, and `destroy`; use the authenticated active gcloud account, with an account override where supported.
- For `init`, `plan`, and `apply`, verify a local backend image built from current relevant build inputs. On a missing or stale image, exit with a clear message containing the exact build command. Do not require a cloud image before Terraform has provisioned Artifact Registry.
- Keep plan review explicit before apply. Preserve private local Terraform state and private backups; never commit state or plans.
- Check whether an image release is needed and report the next `deploy-gcp.py` command. Keep release execution explicit.
- Before destroy, report that the operation removes persistent test data and photo objects, then remove the Cloud Run service through the release/deployment workflow before Terraform destroys its dependencies. Keep teardown explicit and operator initiated.
- Do not require image freshness for destroy.
- Do not add deletion protection to the Cloud DNS zone, records, load-balancer IP,
  load balancer, or certificate. Destroy may remove them; domain registration and the
  demo-token secret remain outside this state.

## Cloud deployment checks

A release is ready for phone connection when the deployed Cloud Run service passes the existing verifier:

- Missing and invalid demo tokens are rejected; valid authenticated health succeeds.
- Production API documentation endpoints are disabled.
- Runtime can create, read, retrieve, scope, and delete a small assessment/photo fixture in Firestore and GCS; cleanup completes.
- The custom API hostname resolves through Cloud DNS to the reserved load-balancer IP,
  has a valid managed TLS certificate, and serves the verified backend.

This is a basic cloud health and storage-readiness check. It does not require a real Muse request or a complete phone journey. Real assessments, follow-ups, reviews, highlights, persistence, and deletion remain available for exploratory testing.

## Persistence and lifecycle

Keep GCP resources, assessment data, and photos until the operator explicitly invokes destroy. Do not add scheduled automatic teardown. Destroy removes the Cloud Run service first and then the Terraform-managed resources, including stored Firestore data and photo objects, consistent with the current Terraform configuration.

## Acceptance criteria

- `terraform-gcp.py` is the documented and supported entry point for all Terraform lifecycle commands.
- The wrapper blocks provisioning commands when no current local backend image exists and prints the build command; it does not require a remote Artifact Registry image before provisioning.
- The wrapper supports infrastructure creation and explicit teardown without requiring an image for destroy.
- Terraform can provision the shared GCP resources; the release workflow can publish and verify a Muse Cloud Run revision.
- Highlight recovery is configured against the stable Cloud Run service URL before enabling highlighting.
- The deployed service passes authenticated health, production-docs, storage CRUD, and device-scope verification.
- The Android Expo Go client reads the HTTPS API URL and matching demo token from the
  root `.env`; no separate `mobile/.env` is required.
- Releasing backend revisions does not require changing the API URL or demo token.
- Resources remain available after the test until explicit teardown.

## Out of scope

- iOS testing, app-store distribution, hosted web frontend, multiple testers, individual accounts, production authentication, hard spending cap, and automatic teardown.
- Performance guarantees or strict latency thresholds.
- Requiring real model analysis or full phone workflow completion as a deployment gate.
