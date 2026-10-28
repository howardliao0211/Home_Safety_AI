# Handoff: connect the frontend to the local API

## Next-session objective

Continue the user's request: **connect the frontend to the API locally** and finish a reviewable, working local development path. The user previously authorized the local backend/frontend setup and browser verification. Do not deploy to GCP; this is local integration work.

## Repository and instructions

- Repo: `/home/hliao211/projects/Home_Safety_AI`
- Read `AGENTS.md`, then `docs/agents/domain.md` and root `CONTEXT.md` before exploring code. The user supplied repo instructions requiring domain guidance before codebase exploration.
- Ticket workflow is documented in `docs/agents/issue-tracker.md`; no ticket is needed unless one becomes necessary.
- Keep `.env` and credentials secret. Never print or copy the Groq key into client config, docs, or output.
- Skill instructions: use the handoff file as a pointer, not as a replacement for repo docs. See Suggested skills below.

## User context

The user initially requested a backend using Groq while keeping the option to switch to Muse AI later. They later asked for Docker/Cloud Run deployment preparation, then asked whether the backend and frontend were ready for deployment/testing. The active task became: **“ok, conntect the frontend to api locally”**. Root `.env` reportedly has working Groq credentials and model selection; no values should be exposed. Cloud Run was not deployed and is out of scope for this handoff.

## Work completed / reported in the prior session

A prior-session summary recorded that the frontend-to-API integration and test scaffolding had been implemented. The git status observed at the beginning of this handoff turn was clean, so changes may have been committed or the workspace may have changed. Inspect current files and git history before repeating work.

Reported integration includes:

- Frontend defaults to API mode; preview fixtures remain available with explicit preview configuration.
- API base URL and optional client demo token configuration; API credentials remain backend-only.
- Stable per-install device identity; separate persistence namespaces for API and preview.
- Frontend client maps backend DTOs, uploads photos/evidence, sends status updates and linked evidence checks, restores latest assessment, loads authenticated private photos, and deletes server data.
- Submitted evidence is immutable after sending; retries use stable IDs and are explicit/manual.
- Backend CORS was configured for local Expo web origins, with no permissive production default.
- Local API browser fixture and connected browser journeys were added, alongside the existing preview browser suite.
- Expo crypto/asset dependencies and config were updated.

Reported checks before the last summary:

- 12 frontend unit tests passed; typecheck passed.
- 45 backend unit/deployment/CORS tests passed; 3 deselected.
- Expo dependency check and Android export passed.
- Browser journeys had **not yet completed** due missing Chromium shared libraries. The issue was environment startup, not yet a demonstrated app failure.
- A project-local attempt to acquire browser libraries was underway. It used `.tools/browser-libs`, `.tools/apt-lists`, `.tools/apt-cache`; ignored tooling only. A shell session was pending (ID 93210), but its state may no longer exist. Inspect `ldd` on the installed Playwright Chromium before relying on that status.

## Immediate next steps

1. Inspect current repository state without exposing secrets:
   - `git status --short`, recent commits, `AGENTS.md`, `docs/agents/domain.md`, `CONTEXT.md`.
   - Verify files described above actually exist and whether changes are committed.
2. Check the browser binary/dependencies. Earlier Playwright Chromium was installed under `/home/hliao211/.cache/ms-playwright`; local extracted libraries were intended under `.tools/browser-libs`. Do not change system packages or weaken APT signature checks. If unavailable, use an authorized project-local route or report the blocker accurately.
3. Run connected API browser suite if the runtime is available:
   - `source scripts/frontend-env.sh`
   - `export LD_LIBRARY_PATH="$PWD/.tools/browser-libs/usr/lib/x86_64-linux-gnu${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"`
   - `cd mobile && npm run test:e2e:api`
   - This suite uses a deterministic test API fixture (not Groq), and its own device IDs/data. It must not be represented as a live model test.
4. Run existing preview browser suite (`npm run test:e2e`) to check preview behavior; its Playwright config was reportedly moved to a separate port (8083).
5. Separately verify the actual local frontend -> local FastAPI -> Groq path with one browser-created assessment, if environment access and quota permit. Start emulators as documented, run API at port 8000, and Expo web at 8081. Never put the Groq key in mobile env/bundles. A Groq quota/rate-limit error is a real provider response; retry only manually after cooldown.
6. Review/update local development docs and README if integration instructions are still missing/outdated. Report any remaining physical-device networking work separately; Android export was tested, but a real phone run was not.
7. Stop only processes/containers started by this work. Emulator data should be preserved.

## Known local setup details from prior session

- Backend: FastAPI under `backend/app`, emulators via `docker compose -f backend/compose.yaml up -d`.
- Backend local port 8000; Firestore emulator 8080; photos emulator 4443.
- Expo web normal port 8081. API browser fixture suite reportedly uses frontend 8082/API 8001. Preview browser suite reportedly uses frontend 8083.
- `source scripts/frontend-env.sh` selects the repository's local Node runtime.
- Local backend venv: `backend/.venv`; deterministic browser API fixture: `backend/tests/api_server.py`.
- Root `.env` reportedly has Groq config and emulator settings. Frontend `mobile/.env` is ignored and intended for public API URL / demo token only.
- Some commands needed sandbox escalation in the prior environment (Docker, Playwright/browser, npm test IPC). Follow current tool approvals and avoid printing environment variables.

## Suggested skills

- `mattpocock-skills:diagnosing-bugs` if the browser integration or local API fails; use its diagnosis loop rather than guessing.
- `mattpocock-skills:codebase-design` if the API/client seam needs further design changes.
- `mattpocock-skills:code-review` after changes are complete, if reviewing the completed integration would help.
- `mattpocock-skills:writing-for-agents` only if modifying `AGENTS.md` or other agent instruction files.
- No need to invoke grilling again; the user already answered prior setup questions and now wants execution.

## Security and reporting

Do not include secrets, actual credential values, or user-specific identifiers in this handoff or final reports. Distinguish deterministic fixture tests from live Groq verification. Final response should summarize the handoff path and any continuation-critical blocker.
