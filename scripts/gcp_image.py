"""Local backend build identity shared by provisioning and releases."""

import hashlib
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCAL_IMAGE = "home-safety-backend:dev"
SOURCE_LABEL = "ai.home-safety.source-sha256"
BUILD_COMMAND = "backend/.venv/bin/python scripts/deploy-gcp.py build"


def build_command(tag):
    return [
        "docker",
        "build",
        "--platform=linux/amd64",
        "--label",
        f"{SOURCE_LABEL}={source_hash()}",
        "--tag",
        tag,
        str(ROOT / "backend"),
    ]


def source_hash():
    backend = ROOT / "backend"
    paths = [
        backend / name
        for name in ("Dockerfile", ".dockerignore", "pyproject.toml", "uv.lock")
    ]
    paths += [
        path
        for path in (backend / "app").rglob("*")
        if path.is_file()
        and "__pycache__" not in path.parts
        and path.suffix != ".pyc"
        and not path.name.startswith(".env")
    ]
    digest = hashlib.sha256()
    for path in sorted(paths):
        digest.update(path.relative_to(backend).as_posix().encode() + b"\0")
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


def require_current_image():
    try:
        result = subprocess.run(
            [
                "docker",
                "image",
                "inspect",
                LOCAL_IMAGE,
                "--format",
                '{{index .Config.Labels "' + SOURCE_LABEL + '"}}',
            ],
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        result = None
    if result is None or result.returncode or result.stdout.strip() != source_hash():
        raise RuntimeError(
            "The current local backend image is missing or stale. Run from the repository root:\n"
            + BUILD_COMMAND
        )
