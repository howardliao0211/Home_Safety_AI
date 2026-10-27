# Backend demo infrastructure

Terraform provisions the approved `home-safety-ai` demo: one `e2-small` VM in
`us-central1-a`, Firestore Standard / Native in `us-central1`, and a private
regional GCS photo bucket. The mobile preview still uses simulated results.
The FastAPI assessment application and Muse integration are separate work.

## Deployment status

The demo resources were destroyed on 2026-10-27 at the user's request. The VM,
boot disk, reserved IP, Firestore database, photo bucket, networking, and runtime
service account have been removed. The former HTTPS address is no longer ours.
The project and enabled APIs remain; Terraform configuration is retained for
future provisioning. Deletion guards remain removed as requested.

The previous deployment passed trusted HTTPS, token enforcement, Firestore/GCS
create/read/delete, anonymous-photo-access denial, and certificate-renewal checks.
No application backend was deployed. Before teardown, live Google API checks
confirmed there were no photo objects/versions or Firestore root collections.

## Before provisioning

Install Terraform >=1.14 and <2.0, Google Cloud CLI, and Python 3. Sign in to the
Google account that can provision resources in the existing, billed project:

```bash
gcloud auth login
gcloud auth list
gcloud projects describe home-safety-ai --account=YOUR_GOOGLE_ACCOUNT
```

The provisioning account needs project permissions to enable services, create
Compute/network/storage/Firestore resources and service accounts, and grant the
runtime IAM roles.
For SSH, it needs IAP tunnel access, OS Login administrator access, and permission
to use the VM service account. Existing owner/admin access may already supply
some of these permissions; Terraform does not grant operator access to itself.

Copy the example and enter the certificate contact email:

```bash
cp deploy/terraform/terraform.tfvars.example deploy/terraform/terraform.tfvars
terraform -chdir=deploy/terraform init
terraform -chdir=deploy/terraform validate
```

Use the wrapper from the repository root. It defaults to the active `gcloud`
account (`hliao211@terpmail.umd.edu` in this checkout). Select another default with
`gcloud config set account EMAIL`, or override one command by adding
`--account=EMAIL` before the Terraform command. The wrapper passes a short-lived
gcloud access token to the provider in the process environment without creating
service-account keys or storing credentials in files:

```bash
python3 scripts/terraform-gcp.py plan -out=demo.tfplan
python3 scripts/terraform-gcp.py apply demo.tfplan
python3 scripts/terraform-gcp.py output
```

The provider explicitly sets `billing_project` and `user_project_override` to
attribute API quota to this project when using gcloud user tokens. This setting
uses the project ID and requires no billing account ID; see the
[provider authentication and quota reference](https://registry.terraform.io/providers/hashicorp/google/latest/docs/guides/provider_reference).

Review the plan before applying it. The first apply enables APIs and can take
several minutes. Only this project's demo resources should change. Do not import
or replace an existing Firestore database without checking its location, mode,
edition, and data first. If `(default)` already exists with the agreed settings,
import it before planning:

```bash
python3 scripts/terraform-gcp.py import google_firestore_database.assessments 'projects/home-safety-ai/databases/(default)'
```

Tokens normally last about an hour; rerun the wrapper for a fresh token if a long
operation expires. The wrapper saves private state snapshots under the ignored
`.tools/terraform-state-backups/` after state-changing commands, including partial
apply failures. Also keep a private backup off this computer to survive disk loss.
Local state belongs to this checkout and is not
shared through Git. Commit `.tf` files and `.terraform.lock.hcl`; never commit
state, saved plans, credentials, real tfvars, or the demo token. A fresh Git clone
does not know which infrastructure already exists: restore state before applying.

## VM and HTTPS

VM setup installs nginx, Python, and isolated Certbot 5.8.0. It generates a random
demo token in `/etc/home-safety-ai/demo-token`, readable only by root. The token
is checked by nginx for every HTTPS route, using `Authorization: Bearer TOKEN`.
This is shared demo access, not individual user authentication. FastAPI must
still scope every assessment and photo operation by `device_id`.

Port 80 serves only ACME certificate challenges; all other HTTP requests return
404. Certbot obtains a trusted certificate for the reserved IP using Let's
Encrypt's short-lived profile. A systemd timer checks hourly and reloads nginx
after renewal. Port 443 opens on successful issuance; no HTTP fallback is used.
Only IAP's source range can reach SSH. FastAPI's port 8000 is not exposed publicly.

Connect using the command printed by `terraform output ssh_command`, adding
`--account=YOUR_GOOGLE_ACCOUNT`. On the VM:

```bash
sudo journalctl -u google-startup-scripts.service --no-pager
sudo systemctl status home-safety-tls.timer home-safety-tls.service
sudo journalctl -u home-safety-tls.service --no-pager
sudo nginx -t
```

Setup runs on every boot and retains the existing token. Certificate setup errors
are logged in the systemd journal; the timer retries after network/ACME failures.
To retry immediately after fixing a problem:

```bash
sudo systemctl start home-safety-tls.service
```

To retrieve the shared token, run `sudo cat /etc/home-safety-ai/demo-token` in your
own SSH terminal. Treat it as a credential and do not paste it in tickets or Git.
From that VM, verify TLS and the gate without printing the token:

```bash
PUBLIC_IP=$(curl -fsS -H 'Metadata-Flavor: Google' http://metadata.google.internal/computeMetadata/v1/instance/network-interfaces/0/access-configs/0/external-ip)
curl -sS -o /dev/null -w '%{http_code}\n' "https://$PUBLIC_IP/infra-healthz"
# Expect 401. An authenticated infrastructure check should return 200.
sudo python3 - "$PUBLIC_IP" <<'PY'
from pathlib import Path
import sys
from urllib.request import Request, urlopen
token = Path('/etc/home-safety-ai/demo-token').read_text().strip()
request = Request(f'https://{sys.argv[1]}/infra-healthz', headers={'Authorization': f'Bearer {token}'})
with urlopen(request) as response:
    print(response.status, response.read().decode())
PY
```

`/infra-healthz` reports infrastructure readiness and explicitly says the app is
not deployed. Other authenticated routes return 502 until FastAPI is running.
When the app is deployed, remove or update this fixed infrastructure marker.
Never use `curl -k` or disable certificate verification in the mobile app.

Test renewal on the VM using Let's Encrypt staging without replacing the live
certificate:

```bash
sudo /opt/home-safety-certbot/bin/certbot renew --dry-run --no-random-sleep-on-renew
```

From the repository root, run the live infrastructure check through IAP:

```bash
gcloud compute ssh home-safety-demo --project=home-safety-ai --zone=us-central1-a --account=YOUR_GOOGLE_ACCOUNT --tunnel-through-iap --command='sudo python3 -' < scripts/verify-gcp-demo.py
```

This verifies trusted TLS and the demo token gate, then creates, reads, and deletes
one temporary non-photo object and one Firestore test document using the VM's
service account. It also checks that anonymous photo access is denied. It prints
no credentials. This is a deployed-infrastructure check, not an application test.

IP certificates last roughly six days, so monitor timer failures. See the
[official Certbot IP-certificate instructions](https://letsencrypt.org/2026/03/11/shorter-certs-certbot.html).
Replacing the VM regenerates its token and certificates; update the demo clients.

## Future FastAPI deployment contract

The VM includes an inactive `home-safety-backend.service` expecting:

- Application files in `/opt/home-safety-ai/current`, readable by `home-safety`.
- A Python venv at `/opt/home-safety-ai/venv` with Uvicorn and the app dependencies.
- ASGI entrypoint `app.main:app`, listening on `127.0.0.1:8000`.
- `/etc/home-safety-ai/backend.env` containing `GOOGLE_CLOUD_PROJECT`,
  `FIRESTORE_DATABASE_ID`, and `PHOTOS_BUCKET`.

Adjust the service to the real app's entrypoint when implemented. Then run
`sudo systemctl enable --now home-safety-backend`. Add the organiser-supplied Muse
credentials to `/etc/home-safety-ai/secrets.env` (root-owned, mode 0600) on the VM
when available; this optional environment file is loaded by systemd and is not
overwritten at boot. Do not
put them in Terraform, VM metadata, the mobile bundle, or Git.

Use the Google Cloud Firestore and Storage server SDKs with default credentials;
they use the attached VM service account without a downloaded key. The runtime
account has `roles/datastore.user` and `roles/logging.logWriter` in this project,
and `roles/storage.objectUser` only on the photos bucket. The logging role lets
the VM startup runner send diagnostics to Cloud Logging. Keep credentials and
image payloads out of application logs. Avoid granting project Editor/Owner.

The bucket has public access prevention, uniform IAM, no object versioning, and
soft delete explicitly disabled. Photos are accessed through the backend; do not
make the bucket public. Firestore stores assessment/finding/checklist metadata
and GCS object names, not image bytes. App deletion must remove linked objects
and documents, handle partial failures, and support retries across both stores.
Infrastructure provisioning does not implement these application operations.

## Costs and teardown

The VM, boot disk, external IPv4 address, bucket storage/operations, Firestore
operations/storage, and network egress can all incur charges. Credit eligibility
and expiration are controlled by Google; Terraform does not verify the balance.

To pause compute after the demo:

```bash
gcloud compute instances stop home-safety-demo --project=home-safety-ai --zone=us-central1-a --account=YOUR_GOOGLE_ACCOUNT
```

Stopping the VM stops CPU/RAM charges but preserves billable disk, IP, and data
resources. It also stops certificate renewal; start the VM and confirm HTTPS
before the next demo.

For removal while retaining Firestore and photos, plan targeted compute removal,
inspect the proposed deletions, then apply the saved plan:

```bash
python3 scripts/terraform-gcp.py plan -destroy -target=google_compute_instance.backend -target=google_compute_address.backend -out=compute-teardown.tfplan
python3 scripts/terraform-gcp.py apply compute-teardown.tfplan
```

Targeting is an exceptional teardown operation. The configuration still declares
the VM/IP, so a later ordinary apply recreates them with a new IP and demo token.
Private storage remains active and can still incur charges.

Deletion guards are removed at the user's request. Firestore deletion protection
is disabled, and the bucket uses `force_destroy = true`, allowing Terraform to
remove it with its contents. A full teardown deletes the database and photos:

```bash
python3 scripts/terraform-gcp.py plan -destroy -out=destroy.tfplan
python3 scripts/terraform-gcp.py apply destroy.tfplan
```

Keep local state until teardown is complete. Required project APIs are left
enabled on destruction so unrelated project use is not disrupted. Terraform
does not delete the project or detach its billing account.
