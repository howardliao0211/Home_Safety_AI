# Local stack script

Complete the [development setup](../../README.md#development-environment),
including dependencies and both environment files. The script uses Python's
standard library and targets Linux/WSL with Bash and Docker Compose.

## Start

From the repository root:

```bash
python3 scripts/local-test.py start
```

The command starts Firestore and photo-storage containers, then waits for the
API and Expo to respond before printing the frontend URL. Services continue
running after the command returns. It reuses the project-local Node environment
from `scripts/frontend-env.sh`. Dependencies must already be installed.

The script runs the API at `http://127.0.0.1:8000` and Expo at
`http://localhost:8081`. It selects API mode and points Expo to that local API
for this session, overriding `EXPO_PUBLIC_DATA_SOURCE` and
`EXPO_PUBLIC_API_URL` without editing `mobile/.env`. The demo token still comes
from your existing frontend environment. Keep it aligned with the backend token
when configured. Provider credentials stay in the backend configuration.

The script also starts the highlight worker
(`python -m app.annotations.local_worker`). Locally there is no Cloud Tasks
queue, so this worker is what runs saved finding highlight attempts; without it
highlights stay queued. The worker exits when MUSE segmentation is not
configured. `start` then reports that it is not running and continues. Unlike
the API, the worker does not reload on code changes; run `stop` and `start`
after changing highlight code.

Calling `start` again reports an already-running managed stack. An occupied
port belonging to another server causes an error; stop that server in its
original terminal first. If only one managed service remains running, run
`stop` and then `start` to restart the stack together.

## Stop

```bash
python3 scripts/local-test.py stop
```

The script stops its own frontend, worker and API process groups, including their child
processes. Process records include a start-time check to avoid targeting an
unrelated process after PID reuse. It then runs Docker Compose `stop` for this
repository's storage containers, including containers started manually.
Firestore can take up to 45 seconds to export its data. Emulator volumes are
retained; this command does not delete assessments or photos. Repeating `stop`
is safe.

## Logs and connection errors

From the repository root:

```bash
tail -f .tools/local-test/backend.log .tools/local-test/worker.log .tools/local-test/frontend.log
# Storage logs:
docker compose -f backend/compose.yaml logs --tail=30
```

Logs append across starts. Process records and logs live in the ignored
`.tools/local-test/` directory. If startup fails, newly launched API, worker and
frontend processes are cleaned up; storage remains available. Run `stop` to stop storage
as well after inspecting the logs.

If the app shows **Retry connecting**, open `http://localhost:8081` on the
same machine as the services, confirm the backend log shows a successful
startup, and check the demo tokens. A model quota error requires a manual retry
after cooldown. For a phone, use the separate
[device testing instructions](manual.md#android-phone); the script's loopback
addresses are intended for a browser on the development machine.

## Verify script changes

From the repository root:

```bash
python3 -m unittest discover -s scripts/tests -p 'test_local_test.py'
```

Lifecycle tests use temporary local HTTP servers and fake Docker/npm commands.
They check repeated start/stop, occupied ports, startup cleanup, an
unconfigured highlight worker, and stale PID records without using the real stack or calling a model provider.
