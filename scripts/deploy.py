#!/usr/bin/env python3
"""Run the GCP phone-test deployment, preserving the existing plan/release gates."""

import argparse
import fcntl
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
PYTHON = ROOT / "backend/.venv/bin/python"
VARIABLES = ROOT / "deploy/terraform/deploy.tfvars.json"


def run(command, *, capture=False):
    if not capture:
        print(f"\n$ {shlex.join(map(str, command))}", flush=True)
    return subprocess.run(
        list(map(str, command)), cwd=ROOT, check=True, text=True, capture_output=capture
    ).stdout


class Deployment:
    def __init__(self, args):
        self.args = args
        account = [f"--account={args.account}"] if args.account else []
        self.terraform = [sys.executable, ROOT / "scripts/terraform-gcp.py", *account]
        self.backend = [PYTHON, ROOT / "scripts/deploy-gcp.py", *account]

    def save_variables(self, **updates):
        values = json.loads(VARIABLES.read_text()) if VARIABLES.exists() else {}
        values.pop("demo_token_initialized", None)
        values.update(updates)
        # No secret values belong in Terraform inputs.
        with open(VARIABLES, "w", opener=lambda path, flags: os.open(path, flags, 0o600)) as file:
            json.dump(values, file, indent=2)
            file.write("\n")
        VARIABLES.chmod(0o600)

    def apply(self):
        run([*self.terraform, "plan", f"-var-file={VARIABLES}", "-out=deploy.tfplan"])
        run([*self.terraform, "apply", "deploy.tfplan"])

    def output(self, name):
        return json.loads(run([*self.terraform, "output", "-json", name], capture=True))

    def stop(self):
        if not (ROOT / "deploy/terraform/terraform.tfstate").is_file():
            raise RuntimeError(
                "Local Terraform state is missing. Restore its private backup before stop."
            )
        run([*self.terraform, "init"])
        command = [*self.terraform, "destroy"]
        if VARIABLES.exists():
            command.append(f"-var-file={VARIABLES}")
        run(command)

    def release(self, *, highlights=False):
        command = [
            *self.backend,
            "release",
            "--provider",
            "muse",
            "--model",
            self.args.model,
        ]
        if highlights:
            command.extend(["--segmentation-model", "sam-3.1"])
        run(command)

    def bootstrap(self):
        # Preserve recovery on repeated deployments; finish refreshes its URL.
        worker_url = ""
        saved_state = {}
        state = ROOT / "deploy/terraform/terraform.tfstate"
        if state.exists():
            saved_state = json.loads(state.read_text())
            if saved_state.get("resources"):
                if "deployment_config" in saved_state.get("outputs", {}):
                    config = self.output("deployment_config")
                    worker_url = config.get("annotation_worker_url", "")
                elif VARIABLES.exists():
                    # Older or partially applied state may not have this output yet.
                    # Keep the saved target until apply can populate the output.
                    worker_url = json.loads(VARIABLES.read_text()).get("annotation_worker_url", "")
        self.save_variables(annotation_worker_url=worker_url, adopt_existing_identity_config=True)
        # GCP reserves deleted queue/database IDs. Allocate fresh IDs only when
        # the resource is absent from state; retain existing resources and data.
        for resource_type, variable, prefix in (
            ("google_cloud_tasks_queue", "annotation_queue_name", "home-safety-annotations"),
            ("google_firestore_database", "firestore_database_id", "home-safety-demo"),
        ):
            existing = [
                r
                for r in saved_state.get("resources", [])
                if r.get("type") == resource_type and r.get("instances")
            ]
            if existing:
                attributes = existing[0]["instances"][0]["attributes"]
                name = attributes.get("name") or attributes["id"].rsplit("/", 1)[-1]
            else:
                name = f"{prefix}-{uuid4().hex[:12]}"
            self.save_variables(**{variable: name})
        self.apply()
        if not worker_url:
            config = self.output("deployment_config")
            account = [f"--account={self.args.account}"] if self.args.account else []
            number = run(
                [
                    "gcloud",
                    *account,
                    "projects",
                    "describe",
                    config["project_id"],
                    "--format=value(projectNumber)",
                ],
                capture=True,
            ).strip()
            if not number.isdecimal():
                raise RuntimeError("Could not resolve the canonical Cloud Run origin.")
            worker_url = f"https://{config['service_name']}-{number}.{config['region']}.run.app"
            self.save_variables(annotation_worker_url=worker_url)
            self.apply()
        run([*self.backend, "configure-auth"])
        run([*self.backend, "secrets", "--provider", "muse"])
        self.release(highlights=True)
        run([*self.backend, "phone-env"])

    def finish(self):
        service_url = run([*self.backend, "service-url"], capture=True).strip()
        if not re.fullmatch(r"https://[a-z0-9.-]+\.run\.app", service_url):
            raise RuntimeError("Cloud Run did not return a valid HTTPS service URL.")
        run([*self.backend, "verify"])
        self.save_variables(
            annotation_worker_url=service_url,
        )
        self.apply()
        self.release(highlights=True)
        run([*self.backend, "verify"])
        run([*self.backend, "phone-env"])
        if self.args.start_expo:
            # npm's Expo launcher reads only root EXPO_PUBLIC_ entries.
            run(
                [
                    "bash",
                    "-c",
                    "source scripts/frontend-env.sh && npm --prefix mobile ci",
                ]
            )
            run(
                [
                    "bash",
                    "-c",
                    "source scripts/frontend-env.sh && "
                    "npm --prefix mobile run start:tunnel -- --go --clear",
                ]
            )
        else:
            print(
                "\nPhone configuration is ready. Start Expo from the repository root:\n"
                "source scripts/frontend-env.sh\n"
                "npm --prefix mobile ci\n"
                "npm --prefix mobile run start:tunnel -- --go --clear"
            )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command",
        choices=["start", "stop"],
        nargs="?",
        default="start",
        help="start deploys (default); stop destroys managed resources and stored data",
    )
    parser.add_argument("--stage", choices=["all", "bootstrap", "finish"])
    parser.add_argument("--model", help="Muse model ID; defaults to MUSE_MAIN_MODEL in root .env")
    parser.add_argument("--account", help="Override the active gcloud account")
    parser.add_argument(
        "--start-expo",
        action="store_true",
        help="Install mobile dependencies and run the tunnel after finish",
    )
    args = parser.parse_args()
    if args.command == "stop" and (args.stage or args.start_expo or args.model):
        parser.error("--stage, --start-expo and --model apply only to start")
    args.stage = args.stage or "all"
    os.umask(0o077)
    lock = None
    try:
        prerequisites = ["terraform", "gcloud"]
        if args.command == "start":
            prerequisites.extend(["uv", "docker"])
        for executable in prerequisites:
            if not shutil.which(executable):
                raise RuntimeError(f"Install {executable} before running deployment.")
        lock_path = ROOT / ".tools/deploy.lock"
        lock_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        lock = lock_path.open("w")
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise RuntimeError("Another deploy.py process is running.") from error
        deployment = Deployment(args)
        if args.command == "stop":
            deployment.stop()
            return 0
        run(["uv", "sync", "--project", "backend", "--extra", "dev", "--locked"])
        # Resolve dotenv using the synced backend environment; never print credentials.
        settings = json.loads(
            run(
                [
                    PYTHON,
                    "-c",
                    "import json, os; from dotenv import dotenv_values; "
                    "v={**dotenv_values('.env'), **os.environ}; "
                    "print(json.dumps({'model': v.get('MUSE_MAIN_MODEL'), "
                    "'has_key': bool(v.get('MUSE_API_KEY'))}))",
                ],
                capture=True,
            )
        )
        args.model = args.model or settings["model"]
        if args.stage in {"all", "bootstrap", "finish"}:
            if not args.model or not re.fullmatch(r"[A-Za-z0-9._/-]+", args.model):
                raise RuntimeError(
                    "Set MUSE_MAIN_MODEL in root .env or pass --model with a valid model ID."
                )
        if args.stage in {"all", "bootstrap"} and not settings["has_key"]:
            raise RuntimeError("Set MUSE_API_KEY in root .env or your environment.")
        run([*deployment.backend, "preflight"])
        run([*deployment.backend, "build"])
        run([*deployment.terraform, "init"])
        run([*deployment.terraform, "validate"])
        if args.stage in {"all", "bootstrap"}:
            deployment.bootstrap()
        if args.stage in {"all", "finish"}:
            deployment.finish()
        return 0
    except (
        RuntimeError,
        OSError,
        ValueError,
        subprocess.CalledProcessError,
        EOFError,
        KeyboardInterrupt,
    ) as error:
        if isinstance(error, subprocess.CalledProcessError):
            # Captured subprocess output may contain secrets; do not echo it.
            message = f"A deployment command failed (exit {error.returncode})."
        else:
            message = str(error) or "Deployment interrupted."
        print(f"\nDeployment stopped: {message}", file=sys.stderr)
        if args.command == "stop":
            print(
                "Teardown may be incomplete. Inspect the plan/state and rerun stop to finish.",
                file=sys.stderr,
            )
        else:
            print(
                "Rerun start to retry deployment, or use --stage finish after a successful bootstrap.\n"
                "Deployment failures do not trigger automatic teardown.",
                file=sys.stderr,
            )
        return 1
    finally:
        if lock is not None:
            lock.close()


if __name__ == "__main__":
    sys.exit(main())
