# Stream “Chat about it” responses

Status: confirmed
Confirmed: 2026-11-01

## Problem and outcome

Users report that “Chat about it” displays an AI response only after generation finishes. Users must instead see the actual answer grow during generation on web, iOS, and Android.

The repository already contains provider streaming, durable partial responses, and frontend polling. This work must establish why incremental output is not visible in the affected environment and fix the relevant frontend, backend, or configuration. Existing code is not evidence that the deployed experience meets this spec.

## Required behavior

- Show a waiting indicator immediately after the question is accepted.
- Display actual AI text progressively in one assistant message, without artificial typing animation or waiting for the complete response.
- Target 500 ms from the backend receiving new provider text to the frontend displaying that text, measured under controlled network conditions. Time waiting for the AI to generate text is excluded. When the provider has no new text, the UI need not manufacture an update.
- Keep existing text visible as more arrives, without duplication, flicker, or older updates overwriting newer text.
- When generation finishes, show the complete answer and remove the writing indicator.
- If generation fails, preserve received text, mark the response incomplete, and offer an explicit retry. Retry generates a fresh answer to the same question and replaces the incomplete attempt, while preserving any separate draft.
- A temporary connection loss preserves visible text and allows observation of the existing job to resume. It must not silently generate another answer.

## Existing interactions to preserve

- Generation continues after leaving the screen or backgrounding the app. Returning loads the latest progress, including completion or failure while away.
- Automatically follow the answer when the user is near the bottom. Otherwise preserve the reading position and offer “Go to newest message.”
- Keep drafts editable and saved while preventing another question until the pending response is resolved under the existing conversation rules.
- Announce status changes accessibly without rereading every text update.
- Preserve finding-scoped conversations and existing ownership, persistence, and job recovery rules.

Adding a Stop button is outside scope.

## Architecture and investigation

Fixes may span frontend, backend, and delivery configuration. Retain the existing durable job architecture and authenticated polling unless investigation demonstrates a necessary architecture change.

Relevant baseline:

- `mobile/app/chat/[assessmentId]/[findingId].tsx` displays partial responses and currently polls active jobs at a 1,000 ms interval.
- `mobile/src/api/backend-client.ts` reads authenticated conversation snapshots.
- `mobile/src/domain/chat.ts` models partial responses and merges versioned snapshots.
- `backend/app/assessments/chat.py` consumes provider text fragments and currently batches partial persistence at a 0.75-second interval.
- `docs/adr/0004-durable-streaming-chat-jobs.md` records durable execution, partial persistence, and authenticated polling.

The current persistence and observation intervals do not establish the confirmed 500 ms delivery target. Evaluate the combined path from provider fragments through persistence and API observation to rendering, rather than changing only a frontend timer. Assess request and persistence load when choosing batching and polling intervals.

If implementation changes an architectural decision, update ADR 0004 with the rationale. In particular, switching to direct client SSE or WebSocket observation would reconsider its polling decision. This spec does not mandate either transport.

## Acceptance criteria

1. On web, iOS, and Android, a controlled slow provider response with multiple text fragments produces multiple visible updates before generation completes. The waiting/writing indicator remains appropriate until the final answer appears.
2. Timing checks measure provider-fragment receipt at the backend through visible frontend rendering and verify the 500 ms delivery target under controlled network conditions. Record the environment and observed timing; a configured 500 ms timer alone is insufficient evidence.
3. The final answer contains the expected text exactly once. Older snapshots cannot erase newer progress or regress a completed response.
4. Failure before any text shows a clear error and retry action. Failure after text preserves the partial answer with an incomplete label. Explicit retry replaces that attempt without duplicating the saved question or losing a separate draft.
5. A temporary connection loss preserves displayed text. Reconnection observes the existing job and its current state without starting a duplicate generation.
6. Leaving and reopening chat, backgrounding and foregrounding, and reloading restore the current saved answer or progress. Completion or failure while away is represented correctly on return.
7. Scrolling follows new text near the bottom and preserves reading position when the user scrolls away. Status announcements do not reread the growing answer on every update.
8. Validate against the connected backend and configured AI provider, alongside automated tests. Preview or mocked streaming alone does not satisfy acceptance. Record platform-specific evidence for web, iOS, and Android and disclose any platform that remains unverified.

## Verification approach

Use controlled provider fragments to make incremental rendering, timing, ordering, and failure checks repeatable. Extend the existing mobile streaming browser tests, connected API/browser tests, chat state tests, and backend streaming tests where they cover the changed behavior. Run appropriate existing checks and perform connected provider verification on all three supported platforms.

Spec confirmation does not imply implementation or deployment has been completed.
