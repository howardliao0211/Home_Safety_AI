#!/usr/bin/env python3
"""Provision or explicitly destroy GCP infrastructure using the selected gcloud account."""

import argparse
import json
import os
import shlex
import shutil
import subprocess
import sys
import time
from pathlib import Path

from gcp_image import require_current_image, source_hash

ROOT = Path(__file__).resolve().parents[1]
DIRECTORY = ROOT / "deploy/terraform"


def backup_state():
    # A failed apply can still modify cloud resources and write valuable state.
    state = DIRECTORY / "terraform.tfstate"
    if state.exists():
        backups = ROOT / ".tools/terraform-state-backups"
        backups.mkdir(mode=0o700, parents=True, exist_ok=True)
        backup = backups / f"home-safety-{time.time_ns()}.tfstate"
        shutil.copyfile(state, backup)
        backup.chmod(0o600)
        print(f"Private local state backup: {backup}", file=sys.stderr)


def release_command(account, command):
    args = [str(ROOT / "backend/.venv/bin/python"), str(ROOT / "scripts/deploy-gcp.py")]
    if account:
        args.append(f"--account={account}")
    return [*args, command]


def read_plan(terraform, plan_file, env):
    result = subprocess.run(
        [*terraform, "show", "-json", plan_file],
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


def inspect_plan(terraform, plan_file, env):
    changes = read_plan(terraform, plan_file, env).get("resource_changes", [])
    for change in changes:
        if (
            change.get("type") == "google_secret_manager_secret"
            and (change["change"].get("before") or {}).get("secret_id")
            == "home-safety-demo-bearer-token"
            and "delete" in change["change"]["actions"]
        ):
            raise RuntimeError(
                "The plan would delete the persistent demo token. Run detach-demo-token and create a fresh plan first."
            )
    return changes


def remove_cloud_run(plan, account, env):
    """Teardown must work even when a partial apply never wrote release outputs."""
    variables = plan["variables"]
    flags = [
        f"--project={variables['project_id']['value']}",
        f"--region={variables['region']['value']}",
        "--quiet",
    ]
    if account:
        flags.append(f"--account={account}")
    # A successful empty list means absent; permission/network failures must stop teardown.
    services = subprocess.run(
        [
            "gcloud",
            "run",
            "services",
            "list",
            *flags,
            "--filter=metadata.name=home-safety-demo",
            "--format=value(metadata.name)",
        ],
        env=env,
        check=True,
        stdout=subprocess.PIPE,
        text=True,
    ).stdout.strip()
    if services:
        if services != "home-safety-demo":
            raise RuntimeError("Unexpected Cloud Run service in teardown lookup.")
        subprocess.run(
            ["gcloud", "run", "services", "delete", "home-safety-demo", *flags],
            env=env,
            check=True,
        )


# Regional resources and the bindings that reference them. A region rebuild
# removes only these; the project, service account, model secrets, Identity
# Platform config and project-wide IAM are shared and retained.
REGIONAL = (
    "google_cloud_scheduler_job.annotation_recovery",
    "google_cloud_tasks_queue.annotations",
    "google_firestore_field.annotation_dispatch",
    "google_firestore_field.chat_dispatch",
    "google_project_iam_member.backend_database",
    "google_firestore_database.assessments",
    "google_storage_bucket_iam_member.backend_photos",
    "google_storage_bucket.photos",
    "google_artifact_registry_repository.backend",
)


def without_field_resets(terraform, plan_command, changes, env):
    """Drop Firestore field resets whose database is deleted; regenerate the plan.

    Resetting field indexes can hang for hours, and the whole database is being
    deleted, so no reset is needed. Returns the regenerated changes.
    """
    databases = {
        c["change"]["before"]["id"]
        for c in changes
        if c.get("type") == "google_firestore_database" and c["change"]["actions"] == ["delete"]
    }
    fields = [
        c["address"]
        for c in changes
        if c.get("type") == "google_firestore_field"
        and c["change"]["actions"] == ["delete"]
        and any(c["change"]["before"]["id"].startswith(db + "/") for db in databases)
    ]
    if not fields:
        return changes
    subprocess.run([*terraform, "state", "rm", *fields], env=env, check=True)
    # State serial changed: regenerate the plan, never apply the stale one.
    subprocess.run(plan_command, env=env, check=True)
    updated = inspect_plan(terraform, plan_command[-1].split("=", 1)[1], env)
    reviewed = {c["address"] for c in changes if c["change"]["actions"] == ["delete"]}
    if any(
        c["change"]["actions"] != ["no-op"]
        and (c["change"]["actions"] != ["delete"] or c["address"] not in reviewed)
        for c in updated
    ):
        raise RuntimeError("Teardown plan changed beyond reviewed deletions; rerun to review it.")
    return updated


def pause_dispatch(plan, account, env):
    """Stop source task delivery and recovery before the service goes away."""
    variables = plan["variables"]
    flags = [f"--location={variables['region']['value']}", f"--project={variables['project_id']['value']}", "--quiet"]
    if account:
        flags.append(f"--account={account}")
    for change in plan.get("resource_changes", []):
        before = change["change"].get("before") or {}
        if change.get("type") == "google_cloud_tasks_queue" and before.get("name"):
            subprocess.run(["gcloud", "tasks", "queues", "pause", before["name"], *flags], env=env, check=True)
        if change.get("type") == "google_cloud_scheduler_job" and before.get("name"):
            subprocess.run(["gcloud", "scheduler", "jobs", "pause", before["name"], *flags], env=env, check=True)


def region_teardown(terraform, extra, account, env):
    """Remove one region's deployment and data while keeping shared resources."""
    plan_command = [
        *terraform,
        "plan",
        "-destroy",
        *extra,
        *(f"-target={address}" for address in REGIONAL),
        "-out=region-teardown.tfplan",
    ]
    subprocess.run(plan_command, env=env, check=True)
    changes = inspect_plan(terraform, "region-teardown.tfplan", env)
    plan = read_plan(terraform, "region-teardown.tfplan", env)
    deleted = [
        c for c in changes if c.get("mode") != "data" and c["change"]["actions"] != ["no-op"]
    ]
    outside = [
        c["address"]
        for c in deleted
        if c["change"]["actions"] != ["delete"]
        or not c["address"].split("[")[0].startswith(REGIONAL)
    ]
    if outside:
        raise RuntimeError(
            "The region teardown plan touches shared resources: " + ", ".join(outside)
        )
    region = plan["variables"]["region"]["value"]
    project = plan["variables"]["project_id"]["value"]
    print(
        f"Region teardown: project {project}, region {region}. Cloud Run, regional "
        "resources and ALL their assessment data and photos are deleted. Model secrets, "
        "Identity Platform accounts and the service account are kept.",
        flush=True,
    )
    subprocess.run([*terraform, "show", "region-teardown.tfplan"], env=env, check=True)
    if input(f"Type rebuild to remove the {region} deployment and its data: ") != "rebuild":
        raise RuntimeError("Region teardown cancelled.")
    backup_state()
    try:
        pause_dispatch(plan, account, env)
        remove_cloud_run(plan, account, env)
        without_field_resets(terraform, plan_command, changes, env)
        return subprocess.run(
            [*terraform, "apply", "region-teardown.tfplan"], env=env, check=False
        ).returncode
    finally:
        backup_state()


def teardown(terraform, extra, account, env):
    print(
        "Destroy removes persistent assessment data and photo objects. The external demo-token secret remains.",
        flush=True,
    )
    plan_command = [*terraform, "plan", "-destroy", *extra, "-out=destroy.tfplan"]
    subprocess.run(plan_command, env=env, check=True)
    changes = inspect_plan(terraform, "destroy.tfplan", env)
    plan = read_plan(terraform, "destroy.tfplan", env)
    subprocess.run([*terraform, "show", "destroy.tfplan"], env=env, check=True)
    if input("Type destroy to remove Cloud Run and apply this destroy plan: ") != "destroy":
        raise RuntimeError("Destroy cancelled.")
    backup_state()
    try:
        remove_cloud_run(plan, account, env)
        without_field_resets(terraform, plan_command, changes, env)
        return subprocess.run([*terraform, "apply", "destroy.tfplan"], env=env).returncode
    finally:
        backup_state()


def report_release(account):
    # Inspection only: provisioning must never silently publish a revision.
    print("Room concept model changes require a release; release reads MUSE_IMAGE_GEN_MODEL from root .env.")
    result = subprocess.run(
        ["terraform", f"-chdir={DIRECTORY}", "output", "-json", "deployment_config"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode:
        print("After provisioning, publish the first Muse revision explicitly:")
        print(
            shlex.join(release_command(account, "release"))
            + " --provider muse --model YOUR_MUSE_MAIN_MODEL"
        )
        return
    config = json.loads(result.stdout)
    command = [
        "gcloud",
        "run",
        "services",
        "describe",
        config["service_name"],
        f"--project={config['project_id']}",
        f"--region={config['region']}",
        "--format=json",
    ]
    if account:
        command.append(f"--account={account}")
    service = subprocess.run(command, capture_output=True, text=True, check=False)
    needed = True
    if service.returncode == 0:
        data = json.loads(service.stdout)
        # Describe the actually serving revision, rather than the latest failed candidate.
        traffic = [t for t in data.get("status", {}).get("traffic", []) if t.get("percent", 0)]
        if len(traffic) == 1 and traffic[0].get("percent") == 100:
            revision_command = [
                "gcloud",
                "run",
                "revisions",
                "describe",
                traffic[0]["revisionName"],
                *command[5:],
            ]
            revision = subprocess.run(revision_command, capture_output=True, text=True, check=False)
            if revision.returncode == 0:
                environment = json.loads(revision.stdout)["spec"]["containers"][0].get("env", [])
                values = {item["name"]: item.get("value") for item in environment}
                needed = (
                    values.get("BACKEND_SOURCE_HASH") != source_hash()
                    or values.get("MODEL_PROVIDER") != "muse"
                    or (
                        bool(config.get("annotation_worker_url"))
                        and (
                            values.get("ANNOTATION_WORKER_URL") != config["annotation_worker_url"]
                            or values.get("MUSE_SEGMENTATION_MODEL") != "sam-3.1"
                        )
                    )
                )
    if needed:
        print("A Muse image release is needed. Run explicitly (select your Muse model):")
        print(
            shlex.join(release_command(account, "release"))
            + " --provider muse --model YOUR_MUSE_MAIN_MODEL"
            + (" --segmentation-model sam-3.1" if config.get("annotation_worker_url") else "")
        )
    else:
        print("The serving Muse revision matches current backend build inputs.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--account", help="Override the active gcloud account")
    parser.add_argument(
        "command",
        choices=[
            "init",
            "plan",
            "apply",
            "destroy",
            "region-teardown",
            "validate",
            "fmt",
            "output",
            "show",
            "detach-demo-token",
        ],
    )
    args, extra = parser.parse_known_args()
    os.umask(0o077)
    command = args.command
    try:
        if command in {"plan", "apply"}:
            require_current_image()
        if command in {"destroy", "region-teardown"} and not (
            DIRECTORY / "terraform.tfstate"
        ).is_file():
            raise RuntimeError(
                "Local Terraform state is missing. Restore its private backup before teardown."
            )
        if command == "apply" and (len(extra) != 1 or extra[0].startswith("-")):
            raise RuntimeError(
                "Apply requires one reviewed saved plan: plan -out=phone.tfplan, then apply phone.tfplan."
            )
        if command in {"destroy", "region-teardown"} and any(
            not arg.startswith("-var-file=") or not arg.removeprefix("-var-file=") for arg in extra
        ):
            raise RuntimeError(
                "Destroy accepts only -var-file=PATH; it creates and displays a destroy plan for confirmation."
            )
        if any(
            arg in {"-destroy", "-auto-approve", "-invoke"}
            or arg.startswith(("-destroy=", "-auto-approve=", "-invoke="))
            for arg in extra
        ):
            raise RuntimeError(
                "Use the explicit destroy command for teardown; automatic approval is unsupported."
            )
        token_command = ["gcloud", "auth", "print-access-token", "--quiet"]
        if args.account:
            token_command.append(f"--account={args.account}")
        token = subprocess.run(
            token_command, check=True, text=True, stdout=subprocess.PIPE
        ).stdout.strip()
        if not token:
            raise RuntimeError("gcloud returned an empty token. Sign in using gcloud auth login.")
        env = os.environ.copy()
        for name in (
            "GOOGLE_CREDENTIALS",
            "GOOGLE_CLOUD_KEYFILE_JSON",
            "GCLOUD_KEYFILE_JSON",
            "TF_CLI_ARGS",
            "TF_CLI_ARGS_apply",
            "TF_CLI_ARGS_plan",
            "TF_CLI_ARGS_destroy",
        ):
            env.pop(name, None)
        env["GOOGLE_OAUTH_ACCESS_TOKEN"] = token
        env["TF_IN_AUTOMATION"] = "1"
        terraform = ["terraform", f"-chdir={DIRECTORY}"]
        if command == "detach-demo-token":
            if extra:
                raise RuntimeError("detach-demo-token takes no arguments.")
            backup_state()
            # Migration only: leave the live token secret and versions untouched.
            return subprocess.run(
                [
                    *terraform,
                    "state",
                    "rm",
                    'google_secret_manager_secret.backend["demo-bearer-token"]',
                ],
                env=env,
            ).returncode
        if command == "destroy":
            return teardown(terraform, extra, args.account, env)
        if command == "region-teardown":
            return region_teardown(terraform, extra, args.account, env)
        if command == "apply":
            # An externally created destroy plan must not bypass ordered teardown.
            changes = inspect_plan(terraform, extra[0], env)
            dependencies = {
                "google_firestore_database",
                "google_storage_bucket",
                "google_service_account",
                "google_cloud_tasks_queue",
                "google_artifact_registry_repository",
                "google_secret_manager_secret",
            }
            if any(
                # Replacement deletes too, e.g. a region or bucket-name change.
                c.get("type") in dependencies and "delete" in c["change"]["actions"]
                for c in changes
            ):
                raise RuntimeError(
                    "Use destroy for teardown so Cloud Run is removed before its dependencies."
                )
            subprocess.run([*terraform, "show", extra[0]], env=env, check=True)
            if input("Type apply to apply this reviewed plan: ") != "apply":
                raise RuntimeError("Apply cancelled.")
        try:
            result = subprocess.run([*terraform, command, *extra], env=env)
        finally:
            if command == "apply":
                backup_state()
        if result.returncode == 0 and command in {"plan", "apply"}:
            report_release(args.account)
        return result.returncode
    except (
        RuntimeError,
        OSError,
        subprocess.CalledProcessError,
        ValueError,
        EOFError,
    ) as error:
        message = (
            str(error)
            if isinstance(error, (RuntimeError, FileNotFoundError))
            else type(error).__name__
        )
        print(f"Provisioning failed: {message}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
