#!/usr/bin/env python3
"""Build and release the backend to Cloud Run after separate Terraform provisioning.

Run with the backend Python environment (httpx and python-dotenv are required).
Secret bytes travel through stdin/stdout pipes, never command arguments or images.
"""

import argparse
import base64
import json
import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import httpx
from dotenv import dotenv_values, set_key

# Also support loading this CLI with importlib from backend integration tests.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from gcp_image import build_command, source_hash

ROOT = Path(__file__).resolve().parents[1]
TERRAFORM = ROOT / "deploy/terraform"


class DeploymentError(Exception):
    pass


@dataclass(frozen=True)
class Config:
    project_id: str
    region: str
    service_name: str
    repository: str
    service_account: str
    photos_bucket: str
    database_id: str
    groq_secret: str
    muse_secret: str = ""
    annotation_tasks_queue: str = ""
    annotation_worker_url: str = ""

    def __post_init__(self):
        # Every regional dependency must be in the region Cloud Run is released to,
        # so a stale input can never pair a new service with another region's queue.
        if not self.repository.startswith(f"{self.region}-docker.pkg.dev/"):
            raise DeploymentError(
                f"Artifact Registry {self.repository} is not in region {self.region}."
            )
        if self.annotation_tasks_queue and f"/locations/{self.region}/" not in (
            self.annotation_tasks_queue
        ):
            raise DeploymentError(
                f"Cloud Tasks queue {self.annotation_tasks_queue} is not in region {self.region}."
            )


class Deployer:
    def __init__(self, config: Config, account: str | None = None):
        self.config = config
        self.account = account
        self.sensitive = set()

    def run(self, command, *, input=None, env=None, missing_ok=False):
        result = subprocess.run(
            command, input=input, text=True, capture_output=True, env=env, check=False
        )
        if result.returncode:
            missing_service = (
                command[1:4] == ["run", "services", "describe"]
                and f"Cannot find service [{self.config.service_name}]" in result.stderr
            )
            if missing_ok and ("NOT_FOUND" in result.stderr or missing_service):
                return None
            # Never relay a cloud/SDK exception body verbatim with known secrets.
            message = result.stderr.strip() or "Command failed"
            for value in self.sensitive:
                message = message.replace(value, "<REDACTED>")
            raise DeploymentError(message)
        return result.stdout.strip()

    def gcloud(self, *arguments, input=None, regional=False, missing_ok=False):
        command = [
            "gcloud",
            *arguments,
            f"--project={self.config.project_id}",
            "--quiet",
        ]
        if regional:
            command.append(f"--region={self.config.region}")
        if self.account:
            command.append(f"--account={self.account}")
        return self.run(command, input=input, missing_ok=missing_ok)

    def describe(self, *, missing_ok=False):
        raw = self.gcloud(
            "run",
            "services",
            "describe",
            self.config.service_name,
            "--format=json",
            regional=True,
            missing_ok=missing_ok,
        )
        return json.loads(raw) if raw else None

    def latest_version(self, secret, *, required=True):
        raw = self.gcloud(
            "secrets",
            "versions",
            "list",
            secret,
            "--filter=state=ENABLED",
            "--sort-by=~createTime",
            "--limit=1",
            "--format=value(name)",
        )
        if not raw:
            if required:
                raise DeploymentError(
                    f"Secret {secret} has no enabled version. Run the secrets command first."
                )
            return None
        version = raw.rsplit("/", 1)[-1]
        if not version.isdecimal():
            raise DeploymentError("Secret Manager did not return a numbered version.")
        return version

    def secret_value(self, secret, version):
        value = self.gcloud("secrets", "versions", "access", version, f"--secret={secret}")
        if not value:
            raise DeploymentError(f"Secret {secret} is empty.")
        self.sensitive.add(value)
        return value

    def add_secret(self, secret, value):
        self.sensitive.add(value)
        name = self.gcloud(
            "secrets",
            "versions",
            "add",
            secret,
            "--data-file=-",
            "--format=value(name)",
            input=value,
        )
        return name.rsplit("/", 1)[-1]

    def publish_secrets(self, env_file, *, provider="groq"):
        values = dotenv_values(env_file)
        key_name = "MUSE_API_KEY" if provider == "muse" else "GROQ_API_KEY"
        secret_name = self.config.muse_secret if provider == "muse" else self.config.groq_secret
        key = os.environ.get(key_name, values.get(key_name))
        if not key or not key.strip():
            raise DeploymentError(
                f"{key_name} is missing from the environment or selected env file."
            )
        version = self.add_secret(secret_name, key)
        print(f"{provider} key uploaded as secret version {version} (value omitted).")

    def configure_auth(self):
        """Fields absent from the installed Terraform provider, configured by REST."""
        access = self.gcloud("auth", "print-access-token").strip()
        payload = {
            "emailPrivacyConfig": {"enableImprovedEmailPrivacy": True},
            "passwordPolicyConfig": {
                "passwordPolicyEnforcementState": "ENFORCE",
                "forceUpgradeOnSignin": False,
                "passwordPolicyVersions": [
                    {
                        "customStrengthOptions": {
                            "minPasswordLength": 9,
                            "maxPasswordLength": 32,
                            "containsUppercaseCharacter": False,
                            "containsLowercaseCharacter": True,
                            "containsNumericCharacter": True,
                            "containsNonAlphanumericCharacter": False,
                        },
                    }
                ],
            },
        }
        response = httpx.patch(
            f"https://identitytoolkit.googleapis.com/admin/v2/projects/{self.config.project_id}/config",
            params={"updateMask": "emailPrivacyConfig,passwordPolicyConfig"},
            headers={
                "Authorization": f"Bearer {access}",
                "X-Goog-User-Project": self.config.project_id,
            },
            json=payload,
            timeout=30,
        )
        if response.status_code != 200:
            raise DeploymentError(
                f"Identity configuration failed (HTTP {response.status_code}); inspect project provider settings."
            )
        print("Enabled email enumeration protection and the required password policy.")

    def build(self, tag):
        self.run(build_command(tag))

    def build_push(self, tag):
        if not re.fullmatch(r"[a-z0-9][a-z0-9_.-]{0,100}", tag) or tag == "latest":
            raise DeploymentError("Use a unique lowercase release tag, not latest.")
        image = f"{self.config.repository}/backend:{tag}"
        print(
            f"Building {image}; only backend application files enter the context.",
            flush=True,
        )
        self.build(image)
        token = self.gcloud("auth", "print-access-token")
        if not token:
            raise DeploymentError("gcloud returned an empty registry access token.")
        self.sensitive.add(token)
        # A temporary Docker config prevents persisting an access token or
        # changing the operator's global credential-helper configuration.
        with tempfile.TemporaryDirectory(prefix="home-safety-docker-") as directory:
            env = {**os.environ, "DOCKER_CONFIG": directory}
            registry = self.config.repository.split("/", 1)[0]
            self.run(
                [
                    "docker",
                    "login",
                    registry,
                    "--username=oauth2accesstoken",
                    "--password-stdin",
                ],
                input=token,
                env=env,
            )
            self.run(["docker", "push", image], env=env)
        digest = self.gcloud(
            "artifacts",
            "docker",
            "images",
            "describe",
            image,
            "--format=value(image_summary.digest)",
        )
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
            raise DeploymentError("Artifact Registry did not return an image digest.")
        return f"{self.config.repository}/backend@{digest}"

    @staticmethod
    def tagged_url(service, tag):
        for traffic in service.get("status", {}).get("traffic", []):
            if traffic.get("tag") == tag and traffic.get("url"):
                return traffic["url"], traffic["revisionName"]
        raise DeploymentError("Cloud Run did not return the candidate revision URL.")

    def release(self, *, model, image=None, tag=None, provider="groq", segmentation_model=""):
        if not model or not re.fullmatch(r"[A-Za-z0-9._/-]+", model):
            raise DeploymentError("Pass --model with a valid model ID for the selected provider.")
        if image and not re.fullmatch(
            re.escape(self.config.repository) + r"/backend@sha256:[0-9a-f]{64}", image
        ):
            raise DeploymentError(
                "--image must be a backend image digest from the provisioned repository."
            )
        model_secret = self.config.muse_secret if provider == "muse" else self.config.groq_secret
        model_key = "MUSE_API_KEY" if provider == "muse" else "GROQ_API_KEY"
        model_version = self.latest_version(model_secret)
        if not self.config.annotation_worker_url or not self.config.annotation_tasks_queue:
            raise DeploymentError(
                "Configure the stable worker URL and apply Terraform for durable account cleanup before release."
            )
        user_token = self.smoke_token()
        previous = self.describe(missing_ok=True)
        if previous:
            self.active_revision(previous)  # This CLI deliberately owns single-revision traffic.
        release_id = (
            "r" + datetime.now(timezone.utc).strftime("%y%m%d-%H%M%S") + "-" + uuid4().hex[:6]
        )
        built_here = image is None
        image = image or self.build_push(tag or release_id)
        environment = {
            "ENVIRONMENT": "production",
            "MODEL_PROVIDER": provider,
            ("MUSE_MAIN_MODEL" if provider == "muse" else "GROQ_MODEL"): model,
            "MODEL_TIMEOUT_SECONDS": "90",
            "GOOGLE_CLOUD_PROJECT": self.config.project_id,
            "FIRESTORE_DATABASE_ID": self.config.database_id,
            "PHOTOS_BUCKET": self.config.photos_bucket,
            "BACKEND_SOURCE_HASH": source_hash() if built_here else "external-image",
        }
        if self.config.annotation_worker_url:
            environment.update(
                {
                    "ANNOTATION_TASKS_QUEUE": self.config.annotation_tasks_queue,
                    "ANNOTATION_WORKER_URL": self.config.annotation_worker_url,
                    "ANNOTATION_WORKER_SERVICE_ACCOUNT": self.config.service_account,
                }
            )
        if segmentation_model:
            if provider != "muse" or not re.fullmatch(r"[A-Za-z0-9._/-]+", segmentation_model):
                raise DeploymentError(
                    "Segmentation requires MUSE and a valid segmentation model ID."
                )
            if not self.config.annotation_tasks_queue or not self.config.annotation_worker_url:
                raise DeploymentError(
                    "Set annotation_worker_url and apply Terraform to provision recovery before enabling highlighting."
                )
            environment.update(
                {
                    "MUSE_SEGMENTATION_MODEL": segmentation_model,
                    "ANNOTATION_TASKS_QUEUE": self.config.annotation_tasks_queue,
                    "ANNOTATION_WORKER_URL": self.config.annotation_worker_url,
                    "ANNOTATION_WORKER_SERVICE_ACCOUNT": self.config.service_account,
                }
            )
        arguments = [
            "run",
            "deploy",
            self.config.service_name,
            f"--image={image}",
            f"--service-account={self.config.service_account}",
            "--allow-unauthenticated",
            "--ingress=all",
            "--cpu=1",
            "--memory=2Gi",
            # 8 x 2 instances admits one assessment's 12 overlapping highlight
            # attempts plus API requests; mask decoding is capped per instance.
            "--concurrency=8",
            "--min=0",
            "--max=2",
            "--timeout=300s",
            "--port=8080",
            "--cpu-throttling",
            f"--revision-suffix={release_id}",
            f"--tag={release_id}",
            "--set-env-vars=" + ",".join(f"{key}={value}" for key, value in environment.items()),
            (f"--set-secrets={model_key}={model_secret}:{model_version}"),
            "--format=json",
        ]
        if previous:
            arguments.append("--no-traffic")
        print("Deploying production revision with numbered secret references.", flush=True)
        candidate = json.loads(self.gcloud(*arguments, regional=True))
        url, revision = self.tagged_url(candidate, release_id)
        # Existing service traffic stays untouched if staging verification fails.
        self.verify_url(url, user_token)
        self.promote(revision)
        current = self.describe()
        try:
            self.verify_url(current["status"]["url"], user_token)
        except (DeploymentError, httpx.HTTPError):
            if previous:
                self.promote(self.active_revision(previous))
                print(
                    "Service-URL verification failed; restored the previous revision.",
                    file=sys.stderr,
                )
            raise
        print(f"Released {revision}: {current['status']['url']}")
        if previous:
            print(f"Previous revision (rollback target): {self.active_revision(previous)}")

    def promote(self, revision):
        self.gcloud(
            "run",
            "services",
            "update-traffic",
            self.config.service_name,
            f"--to-revisions={revision}=100",
            regional=True,
        )

    @staticmethod
    def active_revision(service):
        active = [
            item for item in service["status"].get("traffic", []) if item.get("percent", 0) > 0
        ]
        if len(active) != 1 or active[0]["percent"] != 100 or not active[0].get("revisionName"):
            raise DeploymentError(
                "Expected one revision serving 100% of traffic; inspect existing traffic manually."
            )
        return active[0]["revisionName"]

    def revision_token(self, revision):
        data = json.loads(
            self.gcloud("run", "revisions", "describe", revision, "--format=json", regional=True)
        )
        if (
            data["metadata"]["labels"].get("serving.knative.dev/service")
            != self.config.service_name
        ):
            raise DeploymentError("Revision belongs to a different service.")
        environment = {item["name"]: item for item in data["spec"]["containers"][0]["env"]}
        if environment.get("ENVIRONMENT", {}).get("value") != "production":
            raise DeploymentError("Revision is not configured for production.")
        if "DEMO_BEARER_TOKEN" in environment:
            raise DeploymentError(
                "Legacy demo-auth revisions cannot serve account data. Deploy an account-auth revision."
            )
        if environment.get("GOOGLE_CLOUD_PROJECT", {}).get("value") != self.config.project_id:
            raise DeploymentError("Revision uses the wrong identity project.")
        return self.smoke_token()

    @staticmethod
    def smoke_token():
        settings = {**dotenv_values(ROOT / ".env"), **os.environ}
        token = settings.get("HOME_SAFETY_SMOKE_ID_TOKEN", "")
        if not token:
            email = settings.get("HOME_SAFETY_SMOKE_EMAIL")
            password = settings.get("HOME_SAFETY_SMOKE_PASSWORD")
            api_key = settings.get("EXPO_PUBLIC_FIREBASE_API_KEY")
            if not all((email, password, api_key)):
                raise DeploymentError(
                    "Configure HOME_SAFETY_SMOKE_EMAIL, HOME_SAFETY_SMOKE_PASSWORD and "
                    "the cloud EXPO_PUBLIC_FIREBASE_API_KEY in root .env for a verified test account. "
                    "Alternatively set HOME_SAFETY_SMOKE_ID_TOKEN to a current Firebase ID token."
                )
            try:
                response = httpx.post(
                    "https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword",
                    params={"key": api_key},
                    json={
                        "email": email,
                        "password": password,
                        "returnSecureToken": True,
                    },
                    timeout=30,
                )
                if response.status_code != 200:
                    raise DeploymentError(
                        f"Test-user sign-in failed (HTTP {response.status_code}). Check the cloud Firebase key and test-account credentials."
                    )
                token = response.json()["idToken"]
            except (httpx.HTTPError, ValueError, KeyError) as error:
                raise DeploymentError("Could not sign in the deployment test user.") from error
        try:
            # Early diagnostics only. The backend still verifies the signature,
            # issuer, project, revocation and account state for every protected call.
            payload = token.split(".")[1]
            claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
            expiry = float(claims["exp"])
        except (ValueError, KeyError, IndexError, TypeError) as error:
            raise DeploymentError(
                "The deployment test-user Firebase ID token is malformed."
            ) from error
        if expiry <= datetime.now(timezone.utc).timestamp() + 60:
            raise DeploymentError(
                "The test-user token has expired or is expiring. Configure test-account email/password "
                "for automatic sign-in, or replace HOME_SAFETY_SMOKE_ID_TOKEN."
            )
        if claims.get("email_verified") is not True:
            raise DeploymentError(
                "Verify the deployment test account's email before starting deployment."
            )
        return token

    def verify(self):
        service = self.describe()
        token = self.revision_token(self.active_revision(service))
        self.verify_url(service["status"]["url"], token)

    def delete_service(self):
        if self.describe(missing_ok=True):
            self.gcloud("run", "services", "delete", self.config.service_name, regional=True)
        print("Cloud Run service removed; Terraform dependencies can now be destroyed.")

    def configure_phone(self, env_file):
        service = self.describe()
        token = self.revision_token(self.active_revision(service))
        url = service["status"]["url"]
        self.verify_url(url, token)
        from dotenv import unset_key

        if env_file.exists():
            values = dotenv_values(env_file)
            for name in (
                "EXPO_PUBLIC_DEMO_TOKEN",
                "DEMO_BEARER_TOKEN",
                "EXPO_PUBLIC_AUTH_EMULATOR_URL",
            ):
                if name in values:
                    unset_key(str(env_file), name)
        env_file.touch(mode=0o600, exist_ok=True)
        env_file.chmod(0o600)
        for name, value in {
            "EXPO_PUBLIC_DATA_SOURCE": "api",
            "EXPO_PUBLIC_API_URL": url,
            "EXPO_PUBLIC_FIREBASE_PROJECT_ID": self.config.project_id,
        }.items():
            set_key(str(env_file), name, value)
        print(
            f"Configured {env_file} for the verified API. Set public Firebase app config and restart Expo."
        )

    def rollback(self, revision):
        token = self.revision_token(revision)
        tag = "check-" + uuid4().hex[:8]
        staged = json.loads(
            self.gcloud(
                "run",
                "services",
                "update-traffic",
                self.config.service_name,
                f"--update-tags={tag}={revision}",
                "--format=json",
                regional=True,
            )
        )
        url, _ = self.tagged_url(staged, tag)
        self.verify_url(url, token)
        self.promote(revision)
        self.verify_url(self.describe()["status"]["url"], token)
        print(f"Traffic restored to {revision}; it uses its original pinned secret versions.")

    @staticmethod
    def verify_url(url, token):
        if not re.fullmatch(
            r"https://(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+[a-z0-9](?:[a-z0-9-]*[a-z0-9])?",
            url,
        ):
            raise DeploymentError("Expected an HTTPS API origin without a path.")
        assessment = str(uuid4())
        path = f"/v1/assessments/{assessment}"
        # A tiny fixture is uploaded to verify the runtime's actual Firestore/GCS
        # permissions. It never goes to the model and is deleted after the check.
        png = base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aV8sAAAAASUVORK5CYII="
        )
        with httpx.Client(base_url=url, timeout=180, follow_redirects=False) as client:

            def expect(response, status):
                if response.status_code != status:
                    raise DeploymentError(
                        f"Verification expected HTTP {status}, received {response.status_code} for {response.request.url.path}."
                    )
                return response

            expect(client.get("/health"), 200)
            expect(client.get("/v1/assessments/latest"), 401)
            expect(
                client.get(
                    "/v1/assessments/latest",
                    headers={"Authorization": "Bearer invalid"},
                ),
                401,
            )
            client.headers.update({"Authorization": f"Bearer {token}"})
            expect(client.get("/health"), 200)
            for route in ("/docs", "/redoc", "/openapi.json", "/docs/oauth2-redirect"):
                expect(client.get(route), 404)
            try:
                created = expect(
                    client.post(
                        "/v1/assessments",
                        data={"assessment_id": assessment},
                        files={"photo": ("deployment-check.png", png, "image/png")},
                    ),
                    201,
                ).json()
                expect(client.get(path), 200)
                expect(client.get(path + "/photos/" + created["photo"]["id"]), 200)
                expect(client.get(path, headers={"Authorization": "Bearer invalid"}), 401)
                expect(
                    client.get(
                        path + "/photos/" + created["photo"]["id"],
                        headers={"Authorization": "Bearer invalid"},
                    ),
                    401,
                )
            finally:
                try:
                    expect(client.delete(path), 204)
                except (DeploymentError, httpx.HTTPError) as error:
                    raise DeploymentError(
                        f"Deployment fixture cleanup failed; retry deleting assessment_id={assessment} "
                        f"with the same test account after fixing storage access."
                    ) from error
            expect(client.get(path), 404)
        print(
            "Verified HTTPS, Firebase token gate, disabled API docs and private storage CRUD.",
            flush=True,
        )


def load_config():
    result = subprocess.run(
        ["terraform", f"-chdir={TERRAFORM}", "output", "-json", "deployment_config"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode:
        raise DeploymentError(
            "No deployment_config output. Provision shared infrastructure with Terraform first."
        )
    return Config(**json.loads(result.stdout))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--account", help="gcloud operator account override")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("preflight", help="Check test-user credentials before provisioning")
    sub.add_parser(
        "configure-auth",
        help="Enable account enumeration protection and password policy",
    )
    build = sub.add_parser("build", help="Build a local image without cloud access")
    build.add_argument("--tag", default="home-safety-backend:dev")
    secret = sub.add_parser("secrets", help="Upload the selected backend model key")
    secret.add_argument("--provider", choices=["groq", "muse"], default="groq")
    secret.add_argument("--env-file", type=Path, default=ROOT / ".env")
    release = sub.add_parser(
        "release", help="Build/push and verify a candidate before routing traffic"
    )
    release.add_argument("--provider", choices=["groq", "muse"], default="groq")
    release.add_argument("--segmentation-model", default="")
    release.add_argument(
        "--model",
        help="Model ID; required explicitly for Muse releases",
    )
    release.add_argument("--tag", help="Unique Artifact Registry image tag (otherwise generated)")
    release.add_argument(
        "--image", help="Deploy an existing repository image digest instead of building"
    )
    sub.add_parser("verify", help="Check active revision including storage, without model calls")
    sub.add_parser("status", help="Show URL and serving revision, without configuration secrets")
    sub.add_parser("service-url", help="Print the current Cloud Run service HTTPS URL")
    sub.add_parser(
        "delete-service",
        help="Remove Cloud Run before explicit infrastructure teardown",
    )
    phone = sub.add_parser(
        "phone-env", help="Verify the API endpoint and save client settings privately"
    )
    phone.add_argument("--env-file", type=Path, default=ROOT / ".env")
    rollback = sub.add_parser(
        "rollback", help="Verify an existing revision, then restore its traffic"
    )
    rollback.add_argument("revision")
    args = parser.parse_args()
    os.umask(0o077)
    try:
        if args.command == "preflight":
            Deployer.smoke_token()
            print("Deployment test-user credentials are ready.")
            return 0
        if args.command == "build":
            subprocess.run(build_command(args.tag), check=True)
            print("Current local backend image built. Provision through scripts/terraform-gcp.py.")
            return 0
        deployer = Deployer(load_config(), args.account)
        if args.command == "configure-auth":
            deployer.configure_auth()
        elif args.command == "secrets":
            deployer.publish_secrets(
                args.env_file,
                provider=args.provider,
            )
        elif args.command == "release":
            deployer.release(
                model=args.model
                or (
                    os.environ.get("GROQ_MODEL") or dotenv_values(ROOT / ".env").get("GROQ_MODEL")
                    if args.provider == "groq"
                    else None
                ),
                image=args.image,
                tag=args.tag,
                provider=args.provider,
                segmentation_model=args.segmentation_model,
            )
        elif args.command == "verify":
            deployer.verify()
        elif args.command == "rollback":
            deployer.rollback(args.revision)
        elif args.command == "delete-service":
            deployer.delete_service()
        elif args.command == "phone-env":
            deployer.configure_phone(args.env_file)
        elif args.command == "service-url":
            print(deployer.describe()["status"]["url"])
        else:
            service = deployer.describe()
            print(
                json.dumps(
                    {
                        "url": service["status"]["url"],
                        "revision": deployer.active_revision(service),
                    },
                    indent=2,
                )
            )
        return 0
    except (
        DeploymentError,
        subprocess.CalledProcessError,
        httpx.HTTPError,
        FileNotFoundError,
    ) as error:
        # Avoid printing HTTP requests, response bodies, or subprocess args with payloads.
        message = str(error) if isinstance(error, DeploymentError) else type(error).__name__
        print(f"Deployment failed: {message}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
