#!/usr/bin/env python3
"""Start or stop local storage, FastAPI, the highlight worker, and Expo (Linux/WSL)."""

import argparse
import fcntl
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / ".tools/local-test"
PORTS = {"backend": 8000, "frontend": 8081}
# The worker has no port; it runs saved highlight attempts that local mode never dispatches.
PROCESSES = ("backend", "worker", "frontend")


def identity(pid):
    """Include the kernel start time so stale state cannot target a reused PID."""
    try:
        fields = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
        return None if fields[0] == "Z" else fields[19]
    except FileNotFoundError:
        return None


def load_process(name):
    path = STATE / f"{name}.json"
    if not path.exists():
        return None
    record = json.loads(path.read_text())
    return (
        record
        if record["started"] and identity(record["pid"]) == record["started"]
        else None
    )


def group_alive(pgid):
    for path in Path("/proc").glob("[0-9]*/stat"):
        try:
            fields = path.read_text().rsplit(")", 1)[1].split()
            if fields[0] != "Z" and int(fields[2]) == pgid:
                return True
        except FileNotFoundError:
            continue
    return False


def stop_process(name):
    record = load_process(name)
    if record:
        pid = record["pid"]
        print(f"Stopping {name}…", flush=True)
        try:
            os.killpg(pid, signal.SIGTERM)
            deadline = time.monotonic() + 15
            while group_alive(pid) and time.monotonic() < deadline:
                time.sleep(0.1)
            if group_alive(pid):
                os.killpg(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    (STATE / f"{name}.json").unlink(missing_ok=True)


def compose(*args):
    subprocess.run(
        ["docker", "compose", "-f", str(ROOT / "backend/compose.yaml"), *args],
        cwd=ROOT,
        check=True,
    )


def launch(name, command, directory, env=None):
    with (STATE / f"{name}.log").open("ab") as log:
        process = subprocess.Popen(
            command,
            cwd=directory,
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            env=env,
        )
    record = {"pid": process.pid, "started": identity(process.pid)}
    (STATE / f"{name}.json").write_text(json.dumps(record))
    return process


def wait_ready(name, process, path, timeout=120):
    url = f"http://127.0.0.1:{PORTS[name]}{path}"
    # Local health probes must not go through an HTTP proxy.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"{name} exited. See {STATE / (name + '.log')}")
        try:
            with opener.open(url, timeout=2) as response:
                if response.status == 200:
                    return
        except urllib.error.HTTPError as error:
            # The configured demo token also protects backend health checks.
            if name == "backend" and error.code == 401:
                return
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            pass
        time.sleep(0.5)
    raise RuntimeError(
        f"{name} was not ready after {timeout}s. See {STATE / (name + '.log')}"
    )


def start():
    running = [name for name in PORTS if load_process(name)]
    if len(running) == len(PORTS):
        print(f"Already running. Open http://localhost:{PORTS['frontend']}")
        return
    if running:
        raise RuntimeError(
            "Only part of the managed stack is running. Run stop, then start again."
        )
    for name, port in PORTS.items():
        with socket.socket() as probe:
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                probe.bind(("127.0.0.1", port))
            except OSError as error:
                raise RuntimeError(
                    f"Port {port} ({name}) is occupied. Stop the existing server first; "
                    "this script will not stop an unmanaged process."
                ) from error
    for tool in ("docker", "bash"):
        if not shutil.which(tool):
            raise RuntimeError(
                f"Missing {tool}. Complete README development setup first."
            )
    python = ROOT / "backend/.venv/bin/python"
    if not python.exists() or not (ROOT / "mobile/node_modules").is_dir():
        raise RuntimeError(
            "Install backend and frontend dependencies using the README first."
        )
    if not (ROOT / ".env").exists():
        raise RuntimeError(
            "Configure root .env using the README first."
        )
    # Check npm with the same Node environment used to launch Expo.
    subprocess.run(
        [
            "bash",
            "-c",
            'source "$1"; command -v npm >/dev/null',
            "local-test",
            str(ROOT / "scripts/frontend-env.sh"),
        ],
        check=True,
    )
    compose("up", "-d")
    started = []
    try:
        print("Starting backend…", flush=True)
        backend = launch(
            "backend",
            [
                str(python),
                "-m",
                "uvicorn",
                "app.main:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(PORTS["backend"]),
                "--reload",
            ],
            ROOT / "backend",
        )
        started.append("backend")
        wait_ready("backend", backend, "/health")
        print("Starting highlight worker…", flush=True)
        # A worker left behind by a crashed stack would otherwise run twice.
        stop_process("worker")
        worker = launch(
            "worker",
            [str(python), "-m", "app.annotations.local_worker"],
            ROOT / "backend",
        )
        started.append("worker")
        print("Starting frontend…", flush=True)
        frontend = launch(
            "frontend",
            [
                "bash",
                "-c",
                'source "$1"; exec npm run web -- --localhost --port "$2"',
                "local-test",
                str(ROOT / "scripts/frontend-env.sh"),
                str(PORTS["frontend"]),
            ],
            ROOT / "mobile",
            env={
                **os.environ,
                "EXPO_PUBLIC_DATA_SOURCE": "api",
                "EXPO_PUBLIC_API_URL": f"http://127.0.0.1:{PORTS['backend']}",
            },
        )
        started.append("frontend")
        wait_ready("frontend", frontend, "/")
    except BaseException:
        for name in reversed(started):
            stop_process(name)
        print(
            "Storage remains available. Run stop to stop it gracefully.",
            file=sys.stderr,
        )
        raise
    # The worker exits on purpose when MUSE segmentation is not configured.
    if worker.poll() is not None:
        (STATE / "worker.json").unlink(missing_ok=True)
        print(
            f"Highlight worker is not running; highlights stay queued. "
            f"See {STATE / 'worker.log'}"
        )
    print(
        f"Ready: http://localhost:{PORTS['frontend']}\n"
        f"API docs: http://127.0.0.1:{PORTS['backend']}/docs\n"
        f"Logs: {STATE}\n"
        "Stop: python3 scripts/local-test.py stop"
    )


def stop():
    for name in reversed(PROCESSES):
        stop_process(name)
    compose("stop")
    print("Local stack stopped. Emulator data is preserved.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("start", "stop"))
    args = parser.parse_args()
    os.umask(0o077)
    STATE.mkdir(parents=True, exist_ok=True)
    with (STATE / "lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            parser.exit(
                1,
                "Another local-test command is running. Try again after it finishes.\n",
            )
        try:
            start() if args.command == "start" else stop()
        except (
            OSError,
            ValueError,
            RuntimeError,
            subprocess.CalledProcessError,
        ) as error:
            parser.exit(1, f"{error}\n")
        except KeyboardInterrupt:
            parser.exit(130, "Local startup interrupted.\n")


if __name__ == "__main__":
    main()
