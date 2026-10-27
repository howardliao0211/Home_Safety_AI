"""Run the bundled emulator; export through its API before forwarding shutdown.

The pinned emulator's native export-on-exit fails during JVM shutdown. The
explicit API is also used by Firebase CLI and succeeds while the server is live.
"""

import json
import os
import shutil
import signal
import subprocess
import sys
import uuid
from pathlib import Path
from urllib.request import Request, urlopen

STATE = Path("/state")
MANIFEST = STATE / "current-export"
PROJECT = os.environ.get("GOOGLE_CLOUD_PROJECT", "home-safety-local")
command = [
    "java",
    "-Duser.language=en",
    "-cp",
    "/google-cloud-sdk/platform/cloud-firestore-emulator/cloud-firestore-emulator.jar",
    "com.google.cloud.datastore.emulator.firestore.CloudFirestore",
    "start",
    "--host=0.0.0.0",
    "--port=8080",
    "--database-edition=standard",
    f"--project_id={PROJECT}",
]
if MANIFEST.exists():
    metadata = STATE / MANIFEST.read_text().strip()
    if not metadata.is_file():
        sys.exit("The saved Firestore export is missing; refusing to start with empty data.")
    command.append(f"--import-data={metadata}")

process = subprocess.Popen(command)
stopping = False
export_failed = False


def shutdown(signum, _frame):
    global stopping, export_failed
    if stopping:
        return
    stopping = True
    export_name = "snapshot-" + uuid.uuid4().hex
    try:
        previous = MANIFEST.read_text().strip() if MANIFEST.exists() else None
        body = json.dumps(
            {
                "database": f"projects/{PROJECT}/databases/(default)",
                "export_directory": str(STATE),
                "export_name": export_name,
            }
        ).encode()
        request = Request(
            f"http://127.0.0.1:8080/emulator/v1/projects/{PROJECT}:export",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(request, timeout=25) as response:
            response.read()
        relative = f"{export_name}/{export_name}.overall_export_metadata"
        if not (STATE / relative).is_file():
            raise RuntimeError("Export metadata was not written")
        temporary = STATE / "current-export.tmp"
        temporary.write_text(relative)
        temporary.replace(MANIFEST)
        print("Firestore snapshot saved.", flush=True)
        if previous and Path(previous).parts[0].startswith("snapshot-"):
            shutil.rmtree((STATE / previous).parent, ignore_errors=True)
    except Exception as exc:
        export_failed = True
        print(
            f"Firestore export failed ({type(exc).__name__}); previous snapshot retained.",
            file=sys.stderr,
            flush=True,
        )
    finally:
        process.send_signal(signal.SIGTERM)


signal.signal(signal.SIGTERM, shutdown)
signal.signal(signal.SIGINT, shutdown)
result = process.wait()
sys.exit(1 if export_failed else (0 if stopping else result))
