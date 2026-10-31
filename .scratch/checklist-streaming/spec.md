# Checklist photo overview, household suggestions and streaming finding chat

## Purpose and agreed decisions

Improve the room checklist's photo and summary, make finding highlights communicate
severity, and replace blocking chat generation with a durable job that publishes
real incremental answer text.

The user confirmed these decisions during grilling:

- Show the entire original photo on the checklist, including portrait photos,
  using the same source-aspect approach as finding details.
- Put the photo before the summary.
- Use red for High, yellow for Medium, and green for Low finding highlights.
- Overlay all eligible highlights for open findings on the checklist photo.
  Resolve/dismiss hides that finding's overlay; reopen makes it eligible again.
- Allow translucent masks to overlap and their colors to blend naturally. Do not
  force the highest severity to determine the shared area's color.
- Omit stale highlights that do not match the current finding revision and the
  displayed original photo. Preserve historical evidence in finding details.
- For new assessments with findings, show exactly three high-level suggestion
  bullets based on the visible findings, household profiles and household details.
  Save them with the initial assessment; status changes do not regenerate them.
- For new assessments with no findings, show the qualified no-hazards message and
  no suggestion bullets. Do not invent suggestions just to fill three slots.
- Preserve previously saved summaries as they are. Opening old records does not
  trigger model calls or manufacture bullets.
- Stream actual AI answer fragments into one growing assistant message.
- A durable reply job continues if the user navigates away, closes the app or
  loses connection. Reopening loads the saved partial reply and the same job.
- A failed partial reply remains visible as **Incomplete response**, with manual
  Retry. Retry replaces it with a fresh answer to the same saved question.
  Incomplete answers do not enter later model context.

This document specifies subsequent implementation. No implementation or cloud
provisioning is authorized merely by creating this spec.

## Current implementation and constraints

Relevant existing behavior, verified through read-only inspection:

- `mobile/app/assessment/[id].tsx` renders a summary string before a compact
  `PhotoView`. The compact photo uses a fixed 2.7 aspect ratio and `cover`, cropping
  portrait images (`mobile/src/components/ui.tsx`).
- Finding details use `EvidencePhoto`, with a source-aspect canvas and `contain`.
  It fetches normalized backend evidence so orientation matches saved masks.
- `backend/app/annotations/provider.py` currently bakes orange colors into RGBA
  mask PNGs. Changing a severity badge or frontend color token alone cannot fix
  the image overlays.
- Highlights already run independently and durably. Opening a screen must only
  read saved work; see ADRs 0002 and 0003.
- Assessment summaries are currently strings in model output, persistence, API and
  mobile state. Exactly three bullets need structured data and server validation.
- Household profiles and the saved `household_context` already reach initial
  assessment generation and finding chat. Reuse that context.
- Chat currently persists a question, then performs synchronous `/generate` work
  in a client HTTP request. It saves only the complete answer. Both providers set
  `stream: false`; frontend polling pauses while the initiating request is busy.

## Checklist photo and layout

After the existing screen heading/introduction, render the full original photo
before the summary/suggestion content. Retain the household details, checklist
controls, history access and safety/preview disclosures.

Use one source-aspect canvas for the photo and every overlay:

- Preserve portrait, landscape, square and panoramic aspect ratios without
  cropping or stretching. Tall photos may make the page scroll longer.
- Use the normalized, authenticated backend photo for saved assessments. Do not
  overlay backend masks onto a differently oriented local camera original.
- Match finding details' `EvidencePhoto` behavior, extending/reusing the shared
  rendering rather than maintaining incompatible photo transforms.
- Handle loading, unavailable photo and asset errors without hiding the saved
  summary or checklist. A mask failure must not hide an otherwise readable photo.
- Fit and align every overlay to the same source image rectangle. Do not compute
  each mask's layout independently from a cropped or letterboxed photo view.
- Preserve alignment after window resizing, orientation changes and text scaling.

## Severity colors and combined overview

| Finding severity | Highlight color |
| --- | --- |
| High | Red |
| Medium | Yellow |
| Low | Green |

Apply these colors to individual finding highlights and the checklist overview.
Use translucent fills and distinguishable outlines so the source photo remains
readable, including on light backgrounds. Yellow must remain recognizably yellow;
existing amber/brown badge colors are not a substitute for the requested mask color.
Use textual severity labels and a red/yellow/green legend, rather than color alone.
Low severity must not imply that an object or room has been verified safe.

Support existing stored orange masks as well as new masks. Implementation may
use a reusable alpha/segmentation mask with tinting or another compatible rendering
path. Recoloring must not require another SAM request, a new finding-content
revision or a new annotation attempt. Preserve mask geometry, confidence, reporting,
private asset access and deletion behavior. Historical highlights, when displayed,
use their saved revision's severity rather than pretending to show current content.

### Eligibility and overlap

For each open finding, use at most one highlight: the latest attempt for its
current content revision. Draw it only if that attempt is ready and its saved
photo identity, original-photo kind, orientation and geometry match the displayed
original image. Validate the source identity/digest where available.

- Queued, processing, failed, unavailable and reported attempts are not drawable.
- Do not fall back to an earlier ready attempt when the latest relevant attempt
  is pending, failed or reported.
- Do not borrow a historical initial mask after a content revision or draw a
  follow-up/review-photo mask on the original photo.
- Omit resolved/dismissed findings. Reopening restores eligibility, subject to the
  same validity and reporting checks.
- Render eligible masks together in a stable, deterministic order, without giving
  severity priority. Translucent overlapping regions may blend colors naturally.
  The legend describes the base colors; overlaps do not represent a new severity.
- Existing finding cards remain the way to open details. This change does not
  require selecting an individual finding by tapping an overlapping mask.

Show available highlights progressively; do not wait for every attempt. Keep
coverage understandable, for example **Highlights available for 2 of 4 open
findings**, with the existing AI-generated/unreviewed qualification. Missing masks
must not make an unmarked area appear assessed as safe.

Refresh annotation state while the checklist is focused and the app is active,
including on reopen/foreground return. Ready masks must appear without visiting
finding details. Status changes and reported results must update eligibility.
Load assets independently so one failed mask does not suppress the other masks.
Stop unnecessary polling when nothing is pending or the screen is inactive.
Opening/reopening the checklist never starts or retries segmentation. Existing
explicit retry/report controls in finding details remain available.

## Summary suggestions

For newly generated assessments with at least one finding, the summary area below
the photo contains exactly three distinct, concise suggestion bullets. There is
no additional generated summary paragraph in that area.

The bullets should summarize useful priorities across the assessment, using the
selected household profiles and written household details where relevant. With
no supplied household context, use the visible room and findings to give general
priorities. They are high-level guidance rather than a repetition of every finding
card, three forced hazard categories or three extra checklist items.

Retain existing limits on visible evidence, uncertainty and low-risk guidance.
Do not invent another hazard to fill a bullet or treat household text as proof of
an unseen condition. Keep the existing qualified safety disclosure available.

### Structured output and persistence

- Represent the new suggestions as structured plain-text items, not a paragraph
  containing bullet characters, Markdown or text split heuristically on the client.
- Server validation requires exactly three nonblank items when the initial result
  contains findings and an empty list when it contains none. Reject invalid model
  output through the existing assessment-failure/manual-retry path; do not silently
  drop, pad or synthesize items.
- Bound each item (a maximum of 500 characters is sufficient) and preserve the
  existing assessment storage safeguards.
- Persist the initial suggestions and return/map them through the API and mobile
  storage so restart and another installation show the same content.
- Clearly distinguish legacy summaries from new suggestion data. A compatible
  optional/versioned field can distinguish absent legacy data, an empty new list,
  and a new three-item list. Preserve the existing plain summary for legacy records.
- New zero-finding results display the qualified no-obvious-visible-hazards message
  and photo with no suggestion bullets, empty bullet placeholders or fallback
  generated advice. Zero findings is not a safety certification.
- The rule uses the initial assessment's findings, not the current open count.
  Resolving/dismissing every finding does not remove or regenerate saved bullets.
- Chat, highlight completion, checklist status changes and merely opening a saved
  assessment never regenerate the summary.
- Legacy assessments keep their saved summary text, including on cache-free load.
  Do not call the model on navigation or reinterpret legacy prose as three bullets.

## Durable streaming finding chat

### User-visible behavior

Sending a question accepts a durable backend job promptly. The UI shows queued
progress and then a single assistant message whose text grows as actual model
answer fragments arrive. Do not buffer a full answer and play a typing animation.
Provider fragments may be batched for efficient persistence/rendering; there is
no requirement for a network request or screen-reader announcement per word.

Keep the existing finding title, transcript, locally saved composer, Send, normal
back behavior and safety disclosure. Preserve one unfinished question per finding,
stable question/request IDs, ownership, explicit retries and existing chat limits.
Chat remains advisory and never changes finding content, revisions, status or
highlight attempts.

While a job is queued/running, disable another Send for that finding and allow a
separate unsent draft to remain editable and saved. Do not require the initiating
screen to keep a generation HTTP request open. A new question must not be stranded
between acceptance and a separate app-triggered generation call.

### Job lifecycle and execution

Use a persisted lifecycle equivalent to **queued → running → complete/failed**,
with stable turn, attempt and execution identities, progress ordering and bounded
queue/execution deadlines.

1. Atomically save the accepted question, queued attempt and dispatch intent before
   returning acceptance. A repeated ID/input returns saved state; different input
   under that ID conflicts.
2. Dispatch authenticated durable backend work. Reuse the project's Cloud Tasks,
   recovery-sweep and independent local-worker architecture where appropriate,
   with chat-specific deadlines and processing logic.
3. Claim one execution atomically. Duplicate delivery, reconnection and dispatch
   recovery cannot start the model twice for that attempt.
4. Assemble the original photo, current finding/household state, completed history
   and historical discussion through the existing application-owned context path.
5. Consume provider answer deltas, accumulate bounded text and publish persisted
   partial snapshots with monotonically increasing progress identity/version.
6. Persist a complete final reply only after a successful provider terminal event
   and final validation. EOF, a transport disconnect, partial output, refusal,
   truncation or a length/context error is not successful completion.

Do not rely on an in-process FastAPI background task or phone background execution
for durability. Accepted work continues when its client disconnects, navigates
away or terminates. An independent recovery process reconciles dispatch failures,
expired claims and abandoned operations without requiring an open app.

Define and document concrete bounded queue, stream and worker deadlines during
implementation. Coordinate them with Cloud Run's current 300-second request limit
and configured provider timeouts; do not inherit the highlight worker's unrelated
30-second execution/60-second task deadline. A started attempt that is interrupted
or expires becomes explicitly failed; recovery must not automatically restart a
model stream. Queue delivery recovery before execution is distinct from model retry.

### Incremental persistence and observation

The database is authoritative for queued/running state, published partial text,
errors and final answers. Batch writes rather than rewriting the whole assessment
for every token, and retain atomic ownership/deletion/execution fences. Ensure
partial writes cannot overwrite concurrent checklist, sibling chat or highlight
updates. Include partial text and operation metadata in storage-budget checks;
retain the existing text/history/context limits unless a documented need changes
them. Do not persist an unbounded chunk log or duplicate full answers per update.

The frontend observes persisted progress through authenticated backend endpoints.
Short polling or a resumable authenticated stream may be chosen during
implementation. Both the initiating screen and reopened screens must receive
updates while the job is active; the current `busy` flag must not suppress them.

- While active and connected, publish available partial text on a short bounded
  cadence (target no more than one second between batches), and have the open chat
  display new persisted progress within a further two seconds under normal local
  test conditions. Do not promise a first-token model latency.
- On navigation/restart or connectivity return, read saved state and resume
  observation of the same job. Reconnection may retry reads/subscriptions but
  must not repeat the question or initiate another model generation.
- Ignore out-of-order snapshots/events from older versions or attempts. A late
  partial cannot replace a final answer or overwrite a manual retry's new state.
- Mark a reply complete in the UI only after the complete state is persisted.
- Stop live observation at a terminal state or when the screen is inactive;
  returning to the screen always refetches. Backend work continues independently.
- No Home badges, push notifications, or live updates outside the open chat are
  required by this scope.

### Interrupted replies and manual retry

Keep received partial text after failure and label it **Incomplete response**.
Show the safe error/retry explanation, or the existing non-transient context-limit
explanation when another attempt cannot be sent. An incomplete answer must never
be mistaken for a completed assistant message.

An explicit Retry queues a fresh attempt for the same saved question, without
another user-message record. Clear/reset the previous partial when the retry is
accepted, then grow one replacement assistant answer. Do not append a restarted
answer to the old partial or pretend that a new generation resumes the old stream.
Retain only bounded operation metadata needed for deduplication and recovery.
Preserve a separate new unsent draft throughout retry.

Exclude failed/in-progress partial answers from later model context. Only successful
completed replies become discussion history. Continue to require resolving the
unfinished turn before another question. Provider/model failures do not change
findings or cause automatic model retry or provider fallback.

### Provider boundary

Add a chat-specific streaming adapter path yielding answer text and explicit
terminal success/failure. Retain strict structured generation for initial
assessments and their new suggestion list.

Plain answer-text streaming is the preferred shared contract for chat: do not
show partial JSON, provider event envelopes, reasoning, credentials or control
metadata. Update chat prompts to match text output, accumulate the final string
server-side and validate nonblank content, length and completion before marking
it successful. Keep Muse server-managed history disabled (`store: false`) and
assemble context from saved application records for both providers.

Primary-source verification:

- Meta documents Responses streaming answer deltas and success/failure events in
  its [Responses streaming guide](https://dev.meta.ai/docs/protocols/responses#streaming).
- Groq documents incremental completion deltas in its
  [text-generation guide](https://console.groq.com/docs/text-chat#streaming-a-chat-completion),
  while its [Structured Outputs guide](https://console.groq.com/docs/structured-outputs)
  states that streaming is unsupported with Structured Outputs. Switching the
  existing strict-JSON request to `stream: true` is therefore insufficient.

Verify the exact configured Muse and Groq model combinations with original-photo
input and streaming during implementation; documentation of the separate features
is not proof of every deployed model combination. Do not silently drop the photo,
switch provider, or substitute artificial typing if a combination is unsupported.
Record smoke-test evidence or a concrete compatibility blocker.

### Ownership, deletion and compatibility

Authorize every job creation/retry, history/progress read, worker claim and
publication against the assessment owner, finding membership and active account.
Worker transport authentication does not replace these data-ownership checks.

Assessment/account deletion must remove or invalidate new job/partial records and
dispatch intent using existing retryable deletion. Late worker writes and replayed
tasks cannot recreate deleted data. Sign-out/account switching clears previous
account progress/drafts from view and rejects late UI responses. Keep credentials,
photo bodies and full conversation text out of routine diagnostics.

Completed legacy chat turns remain readable. Old failed turns can use explicit
job-based Retry. Old accepted-but-unstarted turns may offer an explicit Continue
reply action that queues work; opening them alone must not generate. Handle old
running operations through bounded recovery without a duplicate provider call.

## Preview and accessibility

Preview demonstrates independent sample photo overlays and genuine staged sample
updates for queued, partial, completed, interrupted and retry states. Keep preview
state separate from account-backed data, label replies/highlights as simulated,
and require no credentials or real model calls. Fixtures must cover portrait
photos, all three severities, overlapping masks, partial highlight availability,
zero findings, legacy summary and household-aware three-bullet summaries.

Use the current theme and mobile-design skill during implementation. Preserve
Android/iOS safe areas, keyboard/composer access, browser focus and native back
behavior. Respect large text and narrow widths. Announce job phase, completion and
errors without reading the transcript on every fragment. Follow the newest text
only when the user is already at the bottom; preserve older-message reading
position and provide an accessible way to reach the newest text. Use labels and
legend text alongside highlight color. Avoid decorative typing animations.

## Acceptance and verification

1. Portrait, landscape and square photos show their complete content on the
   checklist, ahead of the summary, with source-aligned overlays at narrow and
   wide widths and after rotation. Photo/mask errors preserve readable findings.
2. High/Medium/Low masks are visibly red/yellow/green in finding details and the
   checklist, including existing saved masks, without new segmentation calls.
3. All and only eligible open-finding masks appear progressively on the original
   photo. Overlaps blend naturally in stable order. Resolve/dismiss/report hides
   the relevant overlay; reopen restores only a still-eligible mask. Stale revision,
   wrong-photo and missing/failed/latest-reported masks cannot fall back incorrectly.
4. Opening the checklist observes pending highlights but never creates/retries an
   attempt. One failed mask does not block other overlays or imply room safety.
5. A new result with findings has exactly three validated, saved suggestion items,
   using household profiles/details and visible evidence. A new zero-finding result
   has no suggestions. Legacy summaries remain readable with no navigation model call.
6. Restart, another installation and checklist status changes retain the same
   saved suggestion content. Invalid item counts fail through normal assessment
   recovery rather than being silently repaired or shown as success.
7. A delayed test provider emits multiple answer fragments. Send returns accepted
   job state before provider completion, and the initiating chat shows partial
   text before the terminal event, within the documented observation cadence.
8. Navigate away, terminate/reopen the app and interrupt connectivity during a
   job. Backend progress continues; reopening restores the same persisted partial
   or completed reply without a duplicate question or model execution.
9. Provider failure after partial output, refusal, early EOF, output/context limits
   and expired claims produce distinct recoverable/non-transient states. Partial
   text is labelled incomplete; explicit retry replaces it under the same question
   while preserving a new draft and excluding failed text from future context.
10. Lost acceptance/progress/completion responses, duplicate task delivery,
    concurrent devices, stale progress events and worker restarts cannot duplicate
    completed replies, regress final state or repeat a claimed model attempt.
11. Concurrent chat partial writes, status changes and sibling highlights preserve
    each other's data. Ownership/account switching and deletion races cannot leak
    progress or resurrect records. Storage/context limits remain bounded and visible.
12. Verify preview parity, large text, screen-reader announcements, scrolling while
    text arrives, native keyboard/back behavior and browser focus. Record device
    or provider checks that cannot be performed; do not claim them from unit tests.

Use focused backend tests for structured suggestions, streaming adapters/events,
job dispatch/claims/recovery, ordered persistence, limits, concurrency and deletion.
Use frontend integration checks for full-photo layout, overview eligibility/colors,
legacy/new summaries and initiating/reopened chat observation. Use deterministic
streaming fixtures to test partial states before final output and failure during
streaming. Include a Firestore-backed job/restart/deletion check, appropriate
existing type/unit checks, and native/provider smoke checks where available.

## Implementation references and documentation updates

Read these implementation seams alongside the existing feature specs:

- `mobile/app/assessment/[id].tsx`, `mobile/src/components/ui.tsx`,
  `mobile/src/components/evidence-photo.tsx`, `mobile/src/components/finding-highlight.tsx`.
- `mobile/app/chat/[assessmentId]/[findingId].tsx`, `mobile/src/domain/chat.ts`,
  `mobile/src/domain/model.ts`, `mobile/src/hooks/preview-context.tsx`,
  `mobile/src/api/backend-client.ts`.
- `backend/app/models/schemas.py`, `backend/app/assessments/service.py`,
  `backend/app/assessments/prompts/__init__.py`, `backend/app/assessments/chat.py`.
- `backend/app/models/providers/base.py`, `muse.py`, `groq.py`;
  `backend/app/api/routes.py`, `backend/app/storage/repository.py`.
- `backend/app/annotations/provider.py`, `service.py`, `dispatch.py`,
  `local_worker.py`; `deploy/terraform/main.tf`, `scripts/deploy-gcp.py`.
- `.scratch/finding-chat/spec.md`, `.scratch/eager-finding-segmentation/spec.md`,
  `.scratch/hazard-highlighting/spec.md`, `.scratch/household-details/spec.md`.

During implementation, reconcile `CONTEXT.md`, backend API/local-worker setup,
deployment instructions and demo guidance with the new jobs, partial-state
semantics, colors and summary contract. Extend existing infrastructure rather than
running a separate unmanaged job system. ADRs 0001–0003 remain applicable: backend
owns persistence/deletion, workers are durable, and highlight lifecycles remain
independent of navigation and chat. No contradictory ADR decision was identified.

This spec was prepared from the user's confirmed decisions, repository inspection
and the primary provider documentation linked above. No application code,
implementation tickets, cloud resources or database records were changed, and no
runtime tests or real model calls were run to prepare it.
