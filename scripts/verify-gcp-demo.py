#!/usr/bin/env python3
"""Run as root on the demo VM: verify HTTPS and temporary Firestore/GCS CRUD."""

import argparse
import json
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen
import uuid


def request(url, *, method="GET", data=None, headers=None):
    with urlopen(Request(url, data=data, headers=headers or {}, method=method), timeout=30) as response:
        return response.status, response.read()


def expect_status(url, expected, *, headers=None):
    try:
        status, _ = request(url, headers=headers)
    except HTTPError as error:
        status = error.code
    if status != expected:
        raise RuntimeError(f"Expected HTTP {expected}, received {status}: {url}")


def metadata(path):
    return request(
        f"http://metadata.google.internal/computeMetadata/v1/{path}",
        headers={"Metadata-Flavor": "Google"},
    )[1].decode()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", default="home-safety-ai")
    parser.add_argument("--bucket", default="home-safety-ai-demo-photos")
    args = parser.parse_args()
    if metadata("project/project-id") != args.project:
        raise RuntimeError("This VM is not in the expected project.")

    public_ip = metadata("instance/network-interfaces/0/access-configs/0/external-ip")
    base = f"https://{public_ip}"
    expect_status(f"http://{public_ip}/infra-healthz", 404)
    expect_status(f"{base}/infra-healthz", 401)
    expect_status(f"{base}/infra-healthz", 401, headers={"Authorization": "Bearer invalid"})
    demo_token = Path("/etc/home-safety-ai/demo-token").read_text().strip()
    status, body = request(f"{base}/infra-healthz", headers={"Authorization": f"Bearer {demo_token}"})
    if status != 200 or json.loads(body).get("infrastructure") != "ready":
        raise RuntimeError("Authenticated infrastructure health check failed.")
    print("PASS: trusted HTTPS, HTTP app access blocked, missing/wrong tokens rejected.")

    access_token = json.loads(metadata("instance/service-accounts/default/token"))["access_token"]
    headers = {"Authorization": f"Bearer {access_token}"}
    check_id = uuid.uuid4().hex
    object_name = f"__infra_checks/{check_id}.txt"
    object_url = f"https://storage.googleapis.com/storage/v1/b/{args.bucket}/o/{quote(object_name, safe='')}"
    upload_url = f"https://storage.googleapis.com/upload/storage/v1/b/{args.bucket}/o?uploadType=media&name={quote(object_name, safe='')}"
    document_url = f"https://firestore.googleapis.com/v1/projects/{args.project}/databases/(default)/documents/_infra_checks/{check_id}"
    uploaded = written = False
    try:
        payload = b"home-safety infrastructure check"
        request(upload_url, method="POST", data=payload, headers={**headers, "Content-Type": "text/plain"})
        uploaded = True
        if request(f"{object_url}?alt=media", headers=headers)[1] != payload:
            raise RuntimeError("GCS read did not match the test upload.")
        expect_status(f"https://storage.googleapis.com/{args.bucket}/{object_name}", 403)
        request(document_url, method="PATCH", data=json.dumps({"fields": {"check": {"booleanValue": True}}}).encode(), headers={**headers, "Content-Type": "application/json"})
        written = True
        document = json.loads(request(document_url, headers=headers)[1])
        if document["fields"]["check"]["booleanValue"] is not True:
            raise RuntimeError("Firestore read did not match the test document.")
    finally:
        # These fixtures contain no photos or assessment data. Never print tokens.
        try:
            if written:
                request(document_url, method="DELETE", headers=headers)
        finally:
            if uploaded:
                request(object_url, method="DELETE", headers=headers)
    expect_status(document_url, 404, headers=headers)
    expect_status(object_url, 404, headers=headers)
    print("PASS: VM identity can create/read/delete Firestore documents and private GCS objects.")
    print("PASS: unauthenticated photo access denied; temporary fixtures removed.")


if __name__ == "__main__":
    main()
