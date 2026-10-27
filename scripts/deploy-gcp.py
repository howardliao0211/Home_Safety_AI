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
import secrets
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import httpx
from dotenv import dotenv_values

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
    demo_secret: str


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
            if missing_ok and "NOT_FOUND" in result.stderr:
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

    def publish_secrets(self, env_file, *, rotate_demo_token=False):
        values = dotenv_values(env_file)
        key = os.environ.get("GROQ_API_KEY", values.get("GROQ_API_KEY"))
        if not key or not key.strip():
            raise DeploymentError(
                "GROQ_API_KEY is missing from the environment or selected env file."
            )
        version = self.add_secret(self.config.groq_secret, key)
        print(f"Groq key uploaded as secret version {version} (value omitted).")
        demo_version = self.latest_version(self.config.demo_secret, required=False)
        if demo_version is None or rotate_demo_token:
            token = os.environ.get(
                "DEMO_BEARER_TOKEN", values.get("DEMO_BEARER_TOKEN")
            ) or secrets.token_urlsafe(32)
            demo_version = self.add_secret(self.config.demo_secret, token)
        print(f"Demo token secret version {demo_version} is available (value omitted).")
        print("Existing revisions retain their pinned secret versions until redeployed.")

    def build(self, tag):
        self.run(
            [
                "docker",
                "build",
                "--platform=linux/amd64",
                "--tag",
                tag,
                str(ROOT / "backend"),
            ]
        )

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

    def release(self, *, model, image=None, tag=None):
        if not model or not re.fullmatch(r"[A-Za-z0-9._/-]+", model):
            raise DeploymentError("Set GROQ_MODEL or pass --model with a valid model ID.")
        if image and not re.fullmatch(
            re.escape(self.config.repository) + r"/backend@sha256:[0-9a-f]{64}", image
        ):
            raise DeploymentError(
                "--image must be a backend image digest from the provisioned repository."
            )
        groq_version = self.latest_version(self.config.groq_secret)
        demo_version = self.latest_version(self.config.demo_secret)
        demo_token = self.secret_value(self.config.demo_secret, demo_version)
        previous = self.describe(missing_ok=True)
        if previous:
            self.active_revision(previous)  # This CLI deliberately owns single-revision traffic.
        release_id = (
            "r" + datetime.now(timezone.utc).strftime("%y%m%d-%H%M%S") + "-" + uuid4().hex[:6]
        )
        image = image or self.build_push(tag or release_id)
        environment = {
            "ENVIRONMENT": "production",
            "MODEL_PROVIDER": "groq",
            "GROQ_MODEL": model,
            "MODEL_TIMEOUT_SECONDS": "90",
            "GOOGLE_CLOUD_PROJECT": self.config.project_id,
            "FIRESTORE_DATABASE_ID": self.config.database_id,
            "PHOTOS_BUCKET": self.config.photos_bucket,
        }
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
            "--concurrency=2",
            "--min=0",
            "--max=2",
            "--timeout=300s",
            "--port=8080",
            "--cpu-throttling",
            f"--revision-suffix={release_id}",
            f"--tag={release_id}",
            "--set-env-vars=" + ",".join(f"{key}={value}" for key, value in environment.items()),
            (
                f"--set-secrets=GROQ_API_KEY={self.config.groq_secret}:{groq_version},"
                f"DEMO_BEARER_TOKEN={self.config.demo_secret}:{demo_version}"
            ),
            "--format=json",
        ]
        if previous:
            arguments.append("--no-traffic")
        print("Deploying production revision with numbered secret references.", flush=True)
        candidate = json.loads(self.gcloud(*arguments, regional=True))
        url, revision = self.tagged_url(candidate, release_id)
        # Existing service traffic stays untouched if staging verification fails.
        self.verify_url(url, demo_token)
        self.promote(revision)
        current = self.describe()
        try:
            self.verify_url(current["status"]["url"], demo_token)
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
        reference = environment["DEMO_BEARER_TOKEN"]["valueFrom"]["secretKeyRef"]
        if reference["name"] != self.config.demo_secret or not reference["key"].isdecimal():
            raise DeploymentError("Revision does not pin the expected demo token secret version.")
        return self.secret_value(reference["name"], reference["key"])

    def verify(self):
        service = self.describe()
        token = self.revision_token(self.active_revision(service))
        self.verify_url(service["status"]["url"], token)

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
        if not re.fullmatch(r"https://[a-z0-9.-]+\.run\.app", url):
            raise DeploymentError("Expected a Google-managed HTTPS run.app URL.")
        device, assessment = str(uuid4()), str(uuid4())
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

            expect(client.get("/healthz"), 401)
            expect(client.get("/healthz", headers={"Authorization": "Bearer invalid"}), 401)
            client.headers.update({"Authorization": f"Bearer {token}", "X-Device-ID": device})
            expect(client.get("/healthz"), 200)
            for route in ("/docs", "/redoc", "/openapi.json"):
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
                expect(client.get(path, headers={"X-Device-ID": str(uuid4())}), 404)
            finally:
                try:
                    expect(client.delete(path), 204)
                except (DeploymentError, httpx.HTTPError) as error:
                    raise DeploymentError(
                        f"Deployment fixture cleanup failed; retry deleting assessment_id={assessment} "
                        f"with device_id={device} after fixing storage access."
                    ) from error
            expect(client.get(path), 404)
        print(
            "Verified HTTPS, token gate, disabled API docs, private storage CRUD and device scoping.",
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
    build = sub.add_parser("build", help="Build a local image without cloud access")
    build.add_argument("--tag", default="home-safety-backend:dev")
    secret = sub.add_parser("secrets", help="Upload Groq key and initialize/reuse a demo token")
    secret.add_argument("--env-file", type=Path, default=ROOT / ".env")
    secret.add_argument("--rotate-demo-token", action="store_true")
    release = sub.add_parser(
        "release", help="Build/push and verify a candidate before routing traffic"
    )
    release.add_argument(
        "--model",
        default=os.environ.get("GROQ_MODEL") or dotenv_values(ROOT / ".env").get("GROQ_MODEL"),
    )
    release.add_argument("--tag", help="Unique Artifact Registry image tag (otherwise generated)")
    release.add_argument(
        "--image", help="Deploy an existing repository image digest instead of building"
    )
    sub.add_parser("verify", help="Check active revision including storage, without model calls")
    sub.add_parser("status", help="Show URL and serving revision, without configuration secrets")
    rollback = sub.add_parser(
        "rollback", help="Verify an existing revision, then restore its traffic"
    )
    rollback.add_argument("revision")
    args = parser.parse_args()
    os.umask(0o077)
    try:
        if args.command == "build":
            subprocess.run(
                [
                    "docker",
                    "build",
                    "--platform=linux/amd64",
                    "--tag",
                    args.tag,
                    str(ROOT / "backend"),
                ],
                check=True,
            )
            return 0
        deployer = Deployer(load_config(), args.account)
        if args.command == "secrets":
            deployer.publish_secrets(args.env_file, rotate_demo_token=args.rotate_demo_token)
        elif args.command == "release":
            deployer.release(model=args.model, image=args.image, tag=args.tag)
        elif args.command == "verify":
            deployer.verify()
        elif args.command == "rollback":
            deployer.rollback(args.revision)
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
