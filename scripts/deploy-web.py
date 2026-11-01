#!/usr/bin/env python3
"""Build the existing Expo app and publish a Firebase Hosting browser demo.

Run with backend/.venv/bin/python (python-dotenv and httpx are required).
"""

import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
from urllib.parse import urlsplit

import httpx
from dotenv import dotenv_values, set_key

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / ".tools/web-demo"
PUBLIC_KEYS = (
    "EXPO_PUBLIC_FIREBASE_API_KEY",
    "EXPO_PUBLIC_FIREBASE_APP_ID",
    "EXPO_PUBLIC_FIREBASE_AUTH_DOMAIN",
)


def run(command, *, capture=False, env=None):
    result = subprocess.run(
        list(map(str, command)), cwd=ROOT, env=env, check=True,
        text=True, capture_output=capture,
    )
    return result.stdout.strip() if capture else None


def https_origin(value):
    parsed = urlsplit(value)
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username
            or parsed.password or parsed.path not in ("", "/")
            or parsed.query or parsed.fragment or "|" in value):
        raise ValueError("Use an HTTPS origin without a path, credentials or query.")
    return value.rstrip("/")


def origins(value):
    result = json.loads(value)
    if not isinstance(result, list) or any(not isinstance(item, str) for item in result):
        raise ValueError("CORS_ORIGINS must be a JSON array of origin strings.")
    if any("|" in item or item == "*" for item in result):
        raise ValueError("CORS_ORIGINS must contain explicit origins without '|'.")
    return result


def build_environment(settings, project, api_url):
    # Never inherit preview selectors, emulator URLs or arbitrary public settings.
    env = {key: value for key, value in os.environ.items()
           if not key.startswith("EXPO_PUBLIC_")}
    for key in PUBLIC_KEYS:
        value = settings.get(key)
        if not value or value in ("home-safety-local", "local-emulator-key"):
            raise ValueError(f"Set production {key} in root .env or the environment.")
        env[key] = value
    env.update(
        EXPO_NO_DOTENV="1", EXPO_PUBLIC_DATA_SOURCE="api",
        EXPO_PUBLIC_API_URL=https_origin(api_url),
        EXPO_PUBLIC_FIREBASE_PROJECT_ID=project,
    )
    return env


def hosting_config(site):
    return {"hosting": {
        "site": site, "public": "dist",
        "ignore": ["**/.*", "**/node_modules/**"],
        "rewrites": [{"source": "**", "destination": "/index.html"}],
        # Hosting matches the requested route before the SPA rewrite. Matching
        # only /index.html leaves / and assessment URLs cached for an hour.
        "headers": [{"source": "**", "headers": [
            {"key": "Cache-Control", "value": "no-cache"},
        ]}],
    }}


def cloud_json(args, *command):
    return json.loads(run([
        "gcloud", *command, f"--project={args.project}",
        *([f"--account={args.account}"] if args.account else []),
        "--format=json", "--quiet",
    ], capture=True))


def check_cors(client, api_url, origin):
    # Cloud Run routing can briefly serve the previous revision after promotion.
    for attempt in range(6):
        response = client.options(
            f"{api_url}/v1/assessments", headers={
                "Origin": origin, "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "authorization,content-type",
            },
        )
        if response.status_code == 400 and response.text.startswith("Disallowed CORS"):
            if attempt < 5:
                time.sleep(2)
                continue
            raise ValueError(
                f"Backend CORS preflight rejected {origin}. "
                "Check the serving revision's CORS_ORIGINS, allowed methods and headers."
            )
        response.raise_for_status()
        if response.headers.get("access-control-allow-origin") != origin:
            raise ValueError(f"Backend did not allow browser origin {origin}.")
        return


def configure_cloud(args, client, service, settings, domains):
    # Refuse to move traffic away from an intentionally staged or split release.
    active = [item for item in service["status"].get("traffic", []) if item.get("percent", 0)]
    if (len(active) != 1 or active[0].get("percent") != 100
            or active[0].get("revisionName") != service["status"].get("latestReadyRevisionName")):
        raise ValueError("Finish the pending/split backend release before deploying web.")
    containers = service["spec"]["template"]["spec"]["containers"]
    if len(containers) != 1:
        raise ValueError("Expected the existing single-container backend service.")
    current = {entry["name"]: entry.get("value", "")
               for entry in containers[0].get("env", [])}
    if current.get("GOOGLE_CLOUD_PROJECT") != args.project:
        raise ValueError("The backend identity project does not match --project.")
    merged = list(dict.fromkeys([
        *origins(current.get("CORS_ORIGINS", "[]")),
        *origins(settings.get("CORS_ORIGINS", "[]")),
        *(f"https://{domain}" for domain in domains),
    ]))

    token = run([
        "gcloud", "auth", "print-access-token",
        *([f"--account={args.account}"] if args.account else []),
    ], capture=True)
    headers = {"Authorization": f"Bearer {token}", "x-goog-user-project": args.project}
    auth_url = f"https://identitytoolkit.googleapis.com/admin/v2/projects/{args.project}/config"
    response = client.get(auth_url, headers=headers)
    response.raise_for_status()
    existing = response.json().get("authorizedDomains", [])
    if any(domain not in existing for domain in domains):
        print("Adding Hosting domains to Firebase Authentication.", flush=True)
        response = client.patch(auth_url, params={"updateMask": "authorizedDomains"},
                                headers=headers, json={"authorizedDomains": list(dict.fromkeys([
                                    *existing, *domains,
                                ]))})
        response.raise_for_status()

    sites_url = f"https://firebasehosting.googleapis.com/v1beta1/projects/{args.project}/sites"
    response = client.get(f"{sites_url}/{args.site}", headers=headers)
    if response.status_code == 404:
        print(f"Creating Firebase Hosting site {args.site}.", flush=True)
        response = client.post(sites_url, params={"siteId": args.site}, headers=headers, json={})
    response.raise_for_status()

    value = json.dumps(merged, separators=(",", ":"))
    # Keep future backend releases from dropping browser access.
    env_file = ROOT / ".env"
    env_file.touch(mode=0o600, exist_ok=True)
    env_file.chmod(0o600)
    set_key(str(env_file), "CORS_ORIGINS", value)
    update_needed = origins(current.get("CORS_ORIGINS", "[]")) != merged
    needs_promotion = update_needed
    if not update_needed:
        serving = cloud_json(args, "run", "revisions", "describe", active[0]["revisionName"],
                             f"--region={args.region}")
        serving_env = {entry["name"]: entry.get("value", "")
                       for container in serving["spec"]["containers"]
                       for entry in container.get("env", [])}
        needs_promotion = origins(serving_env.get("CORS_ORIGINS", "[]")) != merged
    if needs_promotion:
        updated = service
        if update_needed:
            print("Updating backend CORS (creates a Cloud Run revision).", flush=True)
            updated = cloud_json(args, "run", "services", "update", args.service,
                                 f"--region={args.region}", f"--update-env-vars=^|^CORS_ORIGINS={value}")
        else:
            print("Activating the saved CORS revision left by the previous deployment.", flush=True)
        # With pinned traffic, latestReady may still name the OLD revision even
        # after a successful configuration update. Verify latestCreated instead.
        revision = updated["status"]["latestCreatedRevisionName"]
        candidate = cloud_json(args, "run", "revisions", "describe", revision,
                               f"--region={args.region}")
        candidate_env = {entry["name"]: entry.get("value", "")
                         for container in candidate["spec"]["containers"]
                         for entry in container.get("env", [])}
        if origins(candidate_env.get("CORS_ORIGINS", "[]")) != merged:
            raise ValueError("New revision does not contain the requested CORS origins; traffic was not changed.")
        cloud_json(args, "run", "services", "update-traffic", args.service,
                   f"--region={args.region}", f"--to-revisions={revision}=100")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", default=None, help="Defaults to the configured Firebase project")
    parser.add_argument("--site", help="Hosting site ID; defaults to project ID")
    parser.add_argument("--service", default="home-safety-demo")
    parser.add_argument("--region", help="Defaults to saved deployment region, then Sydney")
    parser.add_argument("--account", help="gcloud operator account")
    parser.add_argument("--build-only", action="store_true", help="Build locally; do not contact or modify cloud services")
    args = parser.parse_args()
    defaults = json.loads((ROOT / "mobile/eas.json").read_text())["build"]["preview"]["env"]
    settings = {**defaults, **dotenv_values(ROOT / ".env"), **os.environ}
    args.project = args.project or settings.get("EXPO_PUBLIC_FIREBASE_PROJECT_ID")
    args.site = args.site or args.project
    for value in (args.project, args.site):
        if not value or not re.fullmatch(r"[a-z][a-z0-9-]{3,62}", value):
            parser.error("Use valid production --project and --site IDs.")
    saved_file = ROOT / "deploy/terraform/deploy.tfvars.json"
    saved = json.loads(saved_file.read_text()) if saved_file.exists() else {}
    args.region = args.region or saved.get("region", "australia-southeast1")
    tools = ("node",) if args.build_only else ("node", "firebase", "gcloud")
    for tool in tools:
        if not shutil.which(tool):
            parser.error(f"Missing {tool}. See deploy/README.md#browser-demo.")
    api_url = settings.get("EXPO_PUBLIC_API_URL", "")
    service = None
    if not args.build_only:
        print(f"Target: project {args.project}, Hosting site {args.site}, region {args.region}.", flush=True)
        service = cloud_json(args, "run", "services", "describe", args.service,
                             f"--region={args.region}")
        api_url = service["status"]["url"]
        # Check CLI authentication before building or changing the backend.
        run(["firebase", "hosting:sites:list", f"--project={args.project}", "--non-interactive"], capture=True)
    env = build_environment(settings, args.project, api_url)
    OUTPUT.mkdir(parents=True, exist_ok=True)
    config = OUTPUT / "firebase.json"
    config.write_text(json.dumps(hosting_config(args.site), indent=2) + "\n")
    print("Exporting production web app.", flush=True)
    run(["node", ROOT / "scripts/expo.cjs", "export", "--platform", "web",
         "--output-dir", OUTPUT / "dist", "--clear"], env=env)
    if args.build_only:
        print(f"Build ready: {OUTPUT / 'dist'}")
        return
    domains = [f"{args.site}.web.app", f"{args.site}.firebaseapp.com"]
    with httpx.Client(timeout=60) as client:
        client.get(f"{api_url}/health").raise_for_status()
        configure_cloud(args, client, service, settings, domains)
        for domain in domains:
            check_cors(client, api_url, f"https://{domain}")
        print("Publishing web demo.", flush=True)
        run(["firebase", "deploy", "--only", "hosting", f"--project={args.project}",
             "--config", config, "--non-interactive"])
        url = f"https://{domains[0]}"
        response = client.get(url)
        response.raise_for_status()
        if "text/html" not in response.headers.get("content-type", ""):
            raise ValueError("Hosting did not return an HTML page.")
        print(f"\nDemo ready: {url}\nBackend: {api_url}")
        print("Verified Hosting HTML, API health and CORS. Next: sign in and test a room assessment and chat.")


if __name__ == "__main__":
    try:
        main()
    except (ValueError, KeyError, OSError, subprocess.CalledProcessError, httpx.HTTPError) as error:
        # Do not echo API bodies, access tokens, or the loaded environment.
        print(f"Web deployment failed ({type(error).__name__}): {error}", file=sys.stderr)
        sys.exit(1)
