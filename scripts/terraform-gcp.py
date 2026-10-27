#!/usr/bin/env python3
"""Run Terraform using the active gcloud account, with an optional account override."""

import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--account", help="Override the active gcloud account")
    parser.add_argument("command", nargs=argparse.REMAINDER, help="Terraform command and arguments")
    args = parser.parse_args()
    if not args.command:
        parser.error("provide a Terraform command, e.g. plan -out=demo.tfplan")

    # State, plans, and provider files created by this process stay user-private.
    os.umask(0o077)
    directory = Path(__file__).resolve().parents[1] / "deploy" / "terraform"
    token_command = ["gcloud", "auth", "print-access-token", "--quiet"]
    if args.account:
        token_command.append(f"--account={args.account}")
    try:
        token = subprocess.run(
            token_command,
            check=True, text=True, stdout=subprocess.PIPE,
        ).stdout.strip()
    except subprocess.CalledProcessError:
        print("Could not obtain a token. Sign in to the chosen account using gcloud auth login.", file=sys.stderr)
        return 1
    if not token:
        print("gcloud returned an empty token.", file=sys.stderr)
        return 1

    env = os.environ.copy()
    # Use the selected gcloud account rather than unrelated ADC or credential files.
    for name in ("GOOGLE_CREDENTIALS", "GOOGLE_CLOUD_KEYFILE_JSON", "GCLOUD_KEYFILE_JSON"):
        env.pop(name, None)
    env["GOOGLE_OAUTH_ACCESS_TOKEN"] = token
    env["TF_IN_AUTOMATION"] = "1"
    # Tokens are passed only in the child environment, never in CLI arguments/files.
    result = subprocess.run(
        ["terraform", f"-chdir={directory}", *args.command], env=env,
    )
    # Failed applies can still change cloud resources and write valuable state.
    if args.command[0] in {"apply", "destroy", "import", "state"}:
        state = directory / "terraform.tfstate"
        if state.exists():
            backups = directory.parents[1] / ".tools" / "terraform-state-backups"
            backups.mkdir(mode=0o700, parents=True, exist_ok=True)
            backup = backups / f"home-safety-{time.time_ns()}.tfstate"
            shutil.copyfile(state, backup)
            backup.chmod(0o600)
            print(f"Private local state backup: {backup}", file=sys.stderr)
    return result.returncode


if __name__ == "__main__":
    sys.exit(main())
