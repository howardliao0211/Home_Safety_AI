# Backend checks

Install backend dependencies using the
[development setup](../../README.md#backend-dependencies-and-configuration).
Emulator and live-model checks require the storage containers started by the
[local testing instructions](../../README.md#test-the-frontend-and-backend-locally).

From `backend/`:

```bash
uv run ruff check .
uv run ruff format --check .
uv run pytest -q
RUN_EMULATOR_TESTS=1 uv run pytest tests/test_emulators.py -q
RUN_EMULATOR_RESTART_TESTS=1 uv run pytest tests/test_emulator_restart.py -q
```

The default suite uses in-memory test doubles, exercises the real HTTP routes,
and mocks the Muse and Groq HTTP boundaries. Emulator checks use actual Firestore/GCS clients,
retained evidence, linked revisions, status persistence and deletion. The restart
check actually stops/starts both local storage containers, verifying their named
volumes and the Firestore export/import path. A separate
opt-in check makes up to two real calls to the selected provider using the bundled room photo and
cleans its local records afterward:

```bash
RUN_EMULATOR_TESTS=1 RUN_LIVE_MODEL_TESTS=1 \
  uv run pytest tests/test_emulators.py::test_real_model_photo_assessment_and_review -q
```

For a small development quota, add `LIVE_MODEL_INTERVAL_SECONDS=60` to space
the assessment and review requests. This only paces the opt-in smoke test;
the application still requires an explicit manual retry after any failed call.

These verify integration and state behavior, not hazard-detection accuracy.
