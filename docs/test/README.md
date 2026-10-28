# Testing

Complete the [development setup](../../README.md#development-environment) first.
For a live frontend and API session, follow
[Test the frontend and backend locally](../../README.md#test-the-frontend-and-backend-locally).

| Guide | Coverage |
| --- | --- |
| [Local stack script](local-stack.md) | Start/stop commands, background logs, readiness and troubleshooting |
| [Frontend checks](frontend.md) | TypeScript, state tests, preview and connected browser journeys, Expo compatibility and exports |
| [Backend checks](backend.md) | Linting, formatting, API tests, emulator persistence and opt-in live model checks |
| [Manual and device testing](manual.md) | Assessment checklist, preview mode, Android phones and emulators |

Automated browser journeys use deterministic fixtures and do not call Muse or
Groq. Manual connected assessments and the opt-in live model smoke test consume
provider quota. See [demo notes](../demo.md) for recorded checks and limitations.
