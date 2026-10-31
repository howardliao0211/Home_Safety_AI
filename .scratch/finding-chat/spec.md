# Finding chat

## Purpose and agreed scope

Replace the finding screen's AI-initiated follow-up panel with **Chat about it**,
so users can ask further questions about a finding. Remove **Ask AI to check**.
Introduce a saved, text-only conversation per finding, backed by the database.
Each answer uses the finding's previous discussion as context. Chat provides
advice; it does not rewrite the finding or change checklist status.

The user confirmed all six design decisions during grilling, explicitly requiring
database persistence. This spec authorises specification work only; frontend and
backend implementation are a subsequent task.

## Current behavior and required change

`mobile/app/finding/[assessmentId]/[findingId].tsx` currently renders a panel when
`finding.followUp` exists, containing:

- **A CLOSER LOOK** and the AI-generated clarification/photo question, such as
  “Can you safely photograph the top or side of the cabinet where it meets the
  wall? Do not climb or move it.”
- **Add a close-up photo**, **Answer a question**, or **Continue follow-up**.
- **Skip for now**, or a message describing the answered/skipped request.

Remove this entire interactive panel for every finding and follow-up state,
rather than special-casing the cabinet example. Replace it with a consistently
available **Chat about it** entry point. Also remove **Ask AI to check** and copy
that directs users to a photo review or describes the removed controls.

The existing evidence route supports one AI-requested follow-up and photo-based
user reviews. Its successful analysis revises finding content. It is not a chat
API: adding text-only repeated questions requires a separate conversation path.

## Finding screen and navigation

- Show **Chat about it** for every finding, whether open, resolved, or dismissed,
  including findings with no AI-generated follow-up request.
- Place the entry point where the closer-look panel currently appears. Use the
  existing visual language and a clearly labelled navigation control.
- Open a dedicated chat screen scoped by assessment ID and finding ID. Show the
  finding title, saved conversation, multiline text composer, and **Send**.
- An empty conversation explains that users can ask questions about this finding.
  Opening or reopening chat does not call the model, insert a synthetic message,
  or automatically send the old follow-up question.
- Return from chat to the originating finding using normal platform back behavior.
  Preserve its state and the locally saved unsent draft.
- Keep existing evidence, completed follow-up/review panels, photos, content
  revision history, and highlights viewable. Existing discussion need not be
  duplicated as new chat messages to become AI context.
- Keep Mark resolved, Dismiss as not relevant, and Reopen finding working. Update
  supporting copy to explain that chat offers guidance and users decide status.
- The frontend no longer offers new follow-up or photo-review submissions. Remove
  entry points to the legacy evidence composer and guard direct/stale navigation
  so it returns to the finding with access to chat rather than exposing removed
  submission controls. Do not remove access to saved evidence.
- No camera, attachment picker, photo verification, or chat-generated photo upload
  action is included in this change.

## Conversation and AI context

One independent conversation belongs to each finding within its assessment.
Questions about one finding must not pick up another finding's conversation.

For each answer, the backend assembles:

1. The assessment's household profiles and household context.
2. The current finding, including evidence, recommendation, uncertainty, and status.
3. The original room photo through existing private backend photo access.
4. All earlier user messages and successful assistant replies in this finding's
   chat, in their saved order.
5. Earlier completed follow-up/review text and AI feedback for this finding,
   clearly identified as historical discussion.
6. The current user question, included exactly once.

Exclude other findings' conversations, unfinished or failed assistant outputs,
credentials, and unrelated records. Do not automatically resend historical
close-up/review photo binaries. Historical text is context, not a claim that the
model has inspected those historical photos in the current turn.

The assistant answers the user's question using that context and makes remaining
uncertainty explicit. Retain existing home-safety guidance: no safety certification
from photos, no dangerous instructions, and appropriate professional/emergency
guidance when warranted. Previously saved discussion and user text are contextual
data, not instructions that override the assistant's safety behavior.

Do not silently truncate or summarise away prior discussion to fit a model context
window. Before accepting a new question for analysis, enforce documented input,
history/storage, and model-context limits. At a limit, retain the readable history,
show a clear explanation that another question cannot currently be sent, and
preserve the draft. A known context-capacity limit is not a transient Retry error.
Choose and document concrete limits against the supported providers during
implementation; the existing 20-submission limit is not automatically a chat limit.

## Effects on findings

Chat writes only conversation messages and operation metadata. It must not:

- Change finding title, category, severity, evidence, recommendation, or uncertainty.
- Create a finding-content revision or mark the old follow-up answered/skipped.
- Resolve, dismiss, reopen, add, or delete findings.
- Start or retry a highlight attempt or alter existing annotations.

An assistant may suggest an action in its reply. Only the user's existing checklist
controls change status. Chat remains available after a status change, and the next
answer receives the current finding state.

## Database persistence and ownership

Persist the conversation in the existing backend-owned Firestore database. Local
storage alone does not satisfy this requirement. The mobile app reads and writes
chat through authenticated FastAPI endpoints; it does not access Firestore directly.

Persist stable message/turn IDs, the assessment/finding association, user question,
successful assistant reply, stable ordering/timestamps, and operation state needed
for pending, failed, and completed requests. Persist the accepted question before
model generation. Store a reply before presenting the operation as complete.
Expose recoverable pending/failed state after reconnect or restart.

Conversation history is available when the same account reopens the finding after
an app restart or on another device. Refetch on reopen; live cross-device updates
and notifications are outside scope. Unsent drafts remain local and account-scoped,
including across app restart, and are cleared after confirmed submission.

Authorize every read, send, generation, and retry against the authenticated owner
of the assessment and the finding's membership. Clear previous-account chat and
drafts from view on sign-out/account switch. A deleted or inaccessible finding
cannot accept new messages.

Delete conversation records and local drafts with their assessment. Extend the
existing retryable deletion/account-deletion flow to cover any new records and
prevent an in-flight reply from resurrecting deleted data. Do not introduce a
separate indefinite retention policy for chat.

Bound storage without breaking the current Firestore assessment-size safeguards.
Implementation may use separate chat records to keep messages from growing the
atomic assessment/highlight document. Preserve owner scoping and complete deletion
regardless of the physical schema.

## Submission, failures, and retries

- Reject whitespace-only questions. Apply a documented text-length bound on both
  client and server and show an actionable validation message.
- Permit only one pending question per finding, enforced server-side across
  devices. Disable duplicate Send actions while pending; show visible reply progress.
- Use a stable client-generated turn/request identity. Repeating the same accepted
  question ID returns its saved state; reusing it for different input is a conflict.
- A failed reply leaves the saved question visible with **Retry**. Retry targets
  that same turn, with no duplicate question or completed assistant reply.
- Resolve or retry a failed turn before sending another question so discussion
  remains ordered. Preserve any new unsent draft while the failure is resolved.
- If sending fails before acceptance is confirmed, keep the question locally and
  reconcile using the same identity on retry. A lost response must not duplicate
  the accepted database record or trigger a second completed reply.
- Navigation, reopen, and restart read saved operation state; they must not start
  a second generation. Bound interrupted operations so users are not left pending
  indefinitely; surface an interrupted failure eligible for explicit retry.
- Use explicit manual retries, with no automatic model retry or provider fallback.
  Distinguish load failures from an empty conversation and provide load Retry.
- Keep existing findings/history visible when chat fails. Log operation identifiers
  and diagnostic failures using existing conventions, without credentials or image
  payloads. Do not log full conversation text as routine diagnostics.

## Backend and frontend integration

Add a finding-scoped chat contract rather than routing questions through the
existing finding-revision analysis. A proposed API grouping is:

- `GET /v1/assessments/{assessment_id}/findings/{finding_id}/chat` to load history
  and pending/failed operation state.
- `POST /v1/assessments/{assessment_id}/findings/{finding_id}/chat/turns` to accept
  an idempotent text question.
- An explicit generation/retry operation for that turn, following existing
  operation-state conventions where appropriate.

Exact endpoint shapes may follow existing repository conventions. Required
semantics are stable IDs, persisted history, account isolation, ordered context,
server-side pending enforcement, and recoverable manual retries. Do not leak
provider/session state to the client or depend on provider-managed conversation
history. Assemble context from persisted application records for both Muse and
Groq through the shared adapter boundary, with no provider fallback.

Older records without chat load as an empty conversation without a migration or
model call. Existing follow-up/review records remain historical context; no bulk
copy or replay is required. Legacy backend follow-up/review endpoints may remain
for compatibility; removing their frontend entry points does not require deleting
those endpoints or historical evidence.

Preview mode uses its separate local sample state with simulated replies and a
clear preview indication. Demonstrate empty, existing, pending, failed, and
retryable chats without credentials or real model calls. Preview history must not
be mixed into account-backed records.

## Accessibility and presentation

Use the current theme and mobile-design skill during implementation. Support
Android, iOS, and browser preview; preserve safe areas and readable large text.
Keep the composer and Send accessible above the keyboard. Differentiate user and
assistant messages with labels as well as appearance. Announce reply/error state
without repeatedly reading the whole transcript. Preserve older-message reading
position when a reply arrives and provide a way to reach the newest message.
Support browser keyboard focus, platform back behavior, and accessible controls.
Keep the existing AI-generated home-safety disclaimer available.

## Acceptance criteria and verification

1. Every finding has Chat about it. The closer-look heading/question, follow-up
   composer controls, Skip for now, Ask AI to check, and obsolete photo-review
   guidance are absent for all follow-up and finding statuses.
2. Opening chat makes no model request. Back returns to the correct finding and
   preserves an unsent local draft, including after restart.
3. Send a question and a second question referring to its answer. The second
   generation receives the original photo, current finding/household context,
   previous chat, and completed historical discussion in the defined order.
   Another finding's conversation never enters that context.
4. Confirm messages and replies exist in the database. Restart and reopen on
   another installation under the same account: the saved conversation and
   recoverable operation state load correctly.
5. Complete and fail chat operations on open/resolved/dismissed findings. Finding
   content, revisions, checklist status, and highlight attempts remain unchanged.
6. Simulate provider failure, lost send/completion responses, rapid repeated taps,
   concurrent devices, and navigation/restart during generation. Questions remain
   recoverable, pending turns are enforced, and retries create no duplicate
   message/reply or concurrent generation of the same turn.
7. Empty, loading, load-error, sending, reply-failed, completed, invalid-input,
   context-limit, and unavailable-record states are distinct and recoverable as
   appropriate. A context limit retains history without silently omitting messages.
8. Cross-account reads/writes/retries fail. Sign-out hides old conversation/drafts.
   Assessment/account deletion removes chat; an in-flight reply cannot recreate it.
9. Older assessments with no chat still open. Completed evidence/revisions remain
   viewable, and stale evidence routes cannot create new frontend photo submissions.
10. Preview demonstrates the same navigation and states independently. Verify
    narrow screens, large text, keyboard/composer layout, screen-reader labels,
    and native/browser back behavior.

Use focused backend tests for persistence/ownership, context construction,
idempotency/concurrency, operation recovery, deletion races, and unchanged finding
state. Use frontend integration checks for navigation, removed controls, drafts,
and retry states. Run appropriate existing type/unit checks and manually verify
database persistence and native keyboard/back behavior during implementation.

## Documentation and scope reconciliation

During implementation, update root `CONTEXT.md` to describe finding chat, its
advisory role, and replacement of user-facing follow-up/photo-review controls.
Reconcile the previous MVP promises of AI-initiated requests and user-requested
photo checks; remove those promises for the new frontend flow. Update references
in backend API documentation, demo guidance, and affected frontend/history specs
that still direct users to those controls.

No existing ADR forbids this feature. Preserve ADR 0001's backend-owned managed
storage and retryable deletion, ADR 0002's bounded assessment document and durable
highlight behavior, and ADR 0003's independent highlight lifecycle. New chat
writes must not interfere with concurrent status or annotation writes.

## Specification verification

Prepared from the user's confirmed decisions and read-only inspection of the
finding/evidence screens, submission schemas, backend context construction,
API/service restrictions, domain context, and ADRs 0001–0003. No application code
or database schema was changed and no runtime tests were run for this spec.
