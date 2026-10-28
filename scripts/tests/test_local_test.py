"""Lifecycle checks with real local processes and fake Docker/model services."""

import importlib.util
import json
import os
import socket
import subprocess
import sys
import tempfile
import unittest
import warnings
from pathlib import Path
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / "local-test.py"
if not SCRIPT.exists():
    SCRIPT = Path(__file__).with_name("local-test.py")
spec = importlib.util.spec_from_file_location("local_test", SCRIPT)
local = importlib.util.module_from_spec(spec)
spec.loader.exec_module(local)

SERVER = """import http.server, os, sys, time
if os.environ.get("FAIL_FRONTEND") and "--port" not in sys.argv:
    sys.exit(2)
# Gives an exiting worker time to finish before start checks it.
if os.environ.get("FAIL_WORKER"):
    time.sleep(1)
port = int(sys.argv[sys.argv.index("--port") + 1] if "--port" in sys.argv else sys.argv[-1])
class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(401 if self.path == "/healthz" else 200)
        self.end_headers()
        self.wfile.write(b"ready")
http.server.HTTPServer(("127.0.0.1", port), Handler).serve_forever()
"""

WORKER = """import os, sys, time
if os.environ.get("FAIL_WORKER"):
    sys.exit("Configure MUSE and MUSE_SEGMENTATION_MODEL before running the worker.")
time.sleep(600)
"""


class LifecycleTests(unittest.TestCase):
    def setUp(self):
        # start intentionally detaches its children so they outlive the CLI.
        self.warning_context = warnings.catch_warnings()
        self.warning_context.__enter__()
        warnings.simplefilter("ignore", ResourceWarning)
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        for directory in (
            "backend/.venv/bin",
            "backend/app/annotations",
            "mobile/node_modules",
            "scripts",
            "bin",
        ):
            (self.root / directory).mkdir(parents=True)
        (self.root / ".env").touch()
        (self.root / "backend/.venv/bin/python").symlink_to(sys.executable)
        (self.root / "backend/uvicorn.py").write_text(SERVER)
        (self.root / "server.py").write_text(SERVER)
        (self.root / "backend/app/annotations/local_worker.py").write_text(WORKER)
        for name, body in {
            "docker": 'printf "%s\\n" "$*" >> "$TEST_DOCKER_LOG"\n',
            "npm": 'exec "$TEST_PYTHON" "$TEST_SERVER" "${@: -1}"\n',
        }.items():
            path = self.root / "bin" / name
            path.write_text("#!/usr/bin/env bash\n" + body)
            path.chmod(0o755)
        (self.root / "scripts/frontend-env.sh").write_text(":\n")
        self.ports = {}
        for name in ("backend", "frontend"):
            with socket.socket() as probe:
                probe.bind(("127.0.0.1", 0))
                self.ports[name] = probe.getsockname()[1]
        self.patches = [
            patch.object(local, "ROOT", self.root),
            patch.object(local, "STATE", self.root / ".tools/local-test"),
            patch.object(local, "PORTS", self.ports),
            patch.dict(
                os.environ,
                {
                    "PATH": f"{self.root / 'bin'}:{os.environ['PATH']}",
                    "TEST_DOCKER_LOG": str(self.root / "docker.log"),
                    "TEST_PYTHON": sys.executable,
                    "TEST_SERVER": str(self.root / "server.py"),
                },
            ),
        ]
        for item in self.patches:
            item.start()
        local.STATE.mkdir(parents=True)

    def tearDown(self):
        for name in local.PROCESSES:
            local.stop_process(name)
        while True:
            try:
                pid, _ = os.waitpid(-1, os.WNOHANG)
                if not pid:
                    break
            except ChildProcessError:
                break
        for item in reversed(self.patches):
            item.stop()
        self.temp.cleanup()
        self.warning_context.__exit__(None, None, None)

    def test_start_repeat_and_stop_repeat(self):
        local.start()
        records = {name: local.load_process(name) for name in local.PROCESSES}
        self.assertTrue(all(records.values()))
        local.start()
        self.assertEqual(
            records, {name: local.load_process(name) for name in local.PROCESSES}
        )
        local.stop()
        local.stop()
        self.assertTrue(
            all(local.load_process(name) is None for name in local.PROCESSES)
        )
        commands = (self.root / "docker.log").read_text()
        self.assertEqual(commands.count("up -d"), 1)
        self.assertEqual(commands.count("stop"), 2)

    def test_occupied_port_is_not_stopped(self):
        with socket.socket() as server:
            server.bind(("127.0.0.1", self.ports["backend"]))
            server.listen()
            with self.assertRaisesRegex(RuntimeError, "occupied"):
                local.start()
            self.assertEqual(server.getsockname()[1], self.ports["backend"])
        self.assertFalse((self.root / "docker.log").exists())

    def test_failed_frontend_cleans_up_backend(self):
        with (
            patch.dict(os.environ, {"FAIL_FRONTEND": "1"}),
            self.assertRaisesRegex(RuntimeError, "frontend exited"),
        ):
            local.start()
        for name in ("backend", "worker"):
            self.assertIsNone(local.load_process(name))
            self.assertFalse((local.STATE / f"{name}.json").exists())

    def test_unconfigured_worker_does_not_block_start(self):
        with (
            patch.dict(os.environ, {"FAIL_WORKER": "1"}),
            patch("builtins.print") as output,
        ):
            local.start()
        self.assertTrue(local.load_process("backend"))
        self.assertTrue(local.load_process("frontend"))
        self.assertFalse((local.STATE / "worker.json").exists())
        notes = " ".join(str(call.args[0]) for call in output.call_args_list)
        self.assertIn("highlights stay queued", notes)

    def test_stale_record_does_not_kill_unrelated_process(self):
        process = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(60)"],
            start_new_session=True,
        )
        try:
            (local.STATE / "frontend.json").write_text(
                json.dumps(
                    {
                        "pid": process.pid,
                        "started": "stale-start-time",
                    }
                )
            )
            local.stop_process("frontend")
            self.assertIsNone(process.poll())
        finally:
            process.terminate()
            process.wait()


if __name__ == "__main__":
    unittest.main()
