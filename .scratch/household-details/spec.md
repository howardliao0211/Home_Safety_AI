# Optional household details

## Purpose and agreed scope

Add an optional free-text description below the household profile buttons on the
room-photo capture screen. Users can provide details such as ages, mobility needs,
or the types of pets in their household. Send this description as additional
context for the model alongside the selected profiles and room photo.

The user confirmed all seven design decisions in the grilling interview:

1. Always show the textbox; it works independently of profile selection.
2. Use the polished copy below and keep the existing heading and profile labels.
3. Save details with the current draft/assessment, retain them across restart, and
   start each new assessment with a blank description.
4. Use details in the initial assessment and later finding chats; profile buttons
   remain manually selected.
5. Match the existing 3,000-character backend limit, show a counter, and explain
   overlong input without silently cutting it.
6. Show the full description at confirmation and in the saved assessment. Allow
   edits before submission; keep submitted context read-only for stable retries.
7. Trim leading/trailing whitespace at submission, preserve internal spacing and
   line breaks, and treat whitespace-only input as blank.

This spec authorizes specification work. Application implementation is a
subsequent task.

## Capture screen and approved copy

Within `mobile/app/capture.tsx`, retain the section heading:

> Who are you looking out for?

Replace the existing explanatory text with:

> Choose any groups that apply, and add details below if you’d like. Both are optional.

Keep the existing multi-select labels: **Older adult**, **Child**, **Baby**, **Pet**.
Place an always-visible multiline textbox immediately below the profile buttons.

Persistent field label:

> Household details (optional)

Placeholder:

> For example, a 2-year-old, an adult who uses a walker, or two indoor cats.

The label remains visible while typing; the placeholder is an example, never an
initial value. Selecting or deselecting profiles does not hide, clear, or rewrite
the description. Typing does not automatically select or deselect profiles.

All four combinations are valid:

| Profiles | Description | Behavior |
| --- | --- | --- |
| None | Blank | General assessment |
| Selected | Blank | Assessment uses selected household profiles |
| None | Provided | Assessment uses the written context without requiring a group |
| Selected | Provided | Assessment uses both forms of household context |

A room photo remains required by the existing assessment flow. Household details
alone do not enable creating an assessment without a photo.

## Input, normalization and validation

- The textbox accepts multiline plain text.
- Normalize the submitted value by trimming only leading and trailing whitespace.
  Preserve internal spaces and line breaks. Preserve the editable draft while the
  user is typing; do not repeatedly trim it on each keystroke.
- Whitespace-only input normalizes to an empty string and is valid.
- Apply the existing maximum of 3,000 characters to the normalized submitted text.
  Count Unicode characters consistently with the backend, including non-ASCII
  input; a non-BMP character must not count differently between client and server.
- Show a character counter for the normalized value that will be submitted, such
  as **125 / 3,000 characters**. It must remain readable with large text.
- Let users correct overlong text; do not silently truncate typed or pasted input.
  Show an inline error, for example:

  > Keep household details to 3,000 characters or fewer.

- An overlong description prevents proceeding to confirmation and prevents
  creation if the confirmation screen is reached through stale/direct navigation.
  Preserve the entered text, selected profiles and photo. Clear the validation
  error when the input becomes valid.
- Validate again when converting the draft to an assessment; button state alone
  is insufficient. The backend continues to enforce its existing request limit.

## Draft lifecycle and confirmation

Household details belong to one assessment, using the existing local draft and
account-scoped persistence mechanism.

- Save edits durably as part of the current draft. Navigation between capture and
  confirmation, changing the photo or profiles, and an app/browser restart must
  retain the description.
- Include a nonblank description in draft dirty/unsaved-work detection. A draft
  containing text but no photo or selected profile must receive the existing
  discard protection. Keeping/resuming the draft retains the text; confirmed
  discard removes it.
- Creating an assessment copies the normalized description into that assessment
  before clearing the draft or starting network requests.
- Every fresh assessment starts with blank details. Do not copy the previous
  assessment's description into a new draft or create an account-level default.
- Preserve existing account isolation, sign-out cleanup and deletion behavior.
  Older saved drafts/assessments with no description field behave as blank and
  remain usable without a migration or reset.
- Surface storage failures using the existing error conventions. Do not claim an
  edit was saved when persistence failed, or lose local input on a failed save.

On `mobile/app/confirm.tsx`, show selected profiles and the full normalized
household description, preserving readable line breaks. Use **Household details**
as the description label. For blank input, show **No additional details**.

Replace **Change photo or profiles** with a control such as **Edit photo or
household details**, returning to capture with all draft values retained.
The control also allows changing selected profiles through that screen.

If profiles are empty but details are provided, use **No groups selected** for the
profile summary rather than implying that no household context was supplied.
Use the existing general-assessment fallback when both inputs are blank.

Details remain editable until the user creates/submits the assessment. Once the
local assessment is created, freeze its context for upload, analysis and retries,
including after a failed upload or analysis. Do not offer an edit action for a
submitted assessment or change input under an existing assessment ID.

## Saved assessment presentation

Show the full saved description in the opened assessment/checklist screen,
`mobile/app/assessment/[id].tsx`, under a clearly labelled **Household details**
section near the existing household/profile summary. Preserve readable line breaks
and allow normal scrolling for long descriptions. Show **No additional details**
for blank/older records.

The saved description is read-only. Reopening from Home, refreshing server data,
restarting the app, or using another installation under the same account must show
the server-retained description. Existing history list titles/counts need no change.

## Data and model integration

Reuse the existing backend field `household_context` on assessment creation:

- Add household context to mobile `Draft` and `Assessment` state, with a blank
  fallback for older local records. A camelCase mobile field may follow existing
  mapping conventions.
- Carry it through draft creation/resume/editing, draft-to-assessment conversion,
  failure recovery and retries.
- Append the normalized saved value as `household_context` in the existing
  multipart assessment upload. An empty value is valid.
- Include the field in the remote assessment type and `fromServer` mapping so
  server hydration and refresh do not drop or replace saved context.
- Keep server-returned context authoritative for saved assessments. Preserve
  account-scoped ownership and backend-managed Firestore storage.

The backend already accepts this field, stores and returns it, incorporates it
into the creation fingerprint, and supplies it to initial assessment and finding
chat generation. Retain those behaviors rather than inventing a parallel field,
new endpoint or separate context storage. Verify the complete mobile-to-model
path during implementation; showing the textbox alone is insufficient.

The model receives selected profiles and written details as separate context.
Free text may tailor relevant guidance but does not establish visible evidence,
prove a hidden hazard, or override home-safety instructions. Do not automatically
infer profile selections or rewrite user input to reconcile apparent conflicts.
Preserve the existing qualified safety guidance and treatment of household text
as contextual data rather than trusted instructions.

Finding chats use the saved assessment description on every generation. Respect
existing chat context-capacity checks; do not silently omit or summarize household
details to make the conversation fit. Existing legacy evidence analysis already
uses the same assessment context and should remain compatible.

## Preview, accessibility and platforms

Preview supports the same textbox, validation, draft persistence, confirmation and
saved read-only display using its separate local sample state. Keep preview
indication and predefined-result disclosures clear: entering details does not turn
preview into real model analysis or account-backed persistence.

Use the current theme and mobile-design skill during implementation. Support
Android, iOS and browser preview. The field must have an accessible name matching
its visible label, respect text scaling and multiline content, and remain reachable
with the keyboard open. Validation must be visible and announced without reading
the whole form repeatedly. Preserve keyboard focus, normal platform back behavior,
safe areas, and usable controls at narrow widths. Avoid announcing the counter on
every keystroke in a way that interrupts typing.

## Acceptance criteria and verification

1. The approved copy and multiline textbox appear below the unchanged profile
   controls. Details work with zero, one or several profiles selected.
2. Leaving both inputs blank still creates a general assessment. A description
   does not bypass the existing photo requirement.
3. Details survive capture/confirmation navigation, photo/profile changes, draft
   resume and app/browser restart. A text-only draft gets discard protection;
   confirmed discard removes it, and a fresh draft starts blank.
4. Confirmation displays the complete normalized text and permits returning to
   edit it without losing other input. Details-only input has an accurate summary.
5. Whitespace-only input is accepted as blank. Outer whitespace is trimmed at
   submission; internal spaces/newlines are preserved. Test boundary lengths,
   Unicode characters and pasted overlong input. Invalid input stays editable and
   does not create or upload an assessment.
6. The upload includes the normalized `household_context`. A captured provider
   request receives it alongside the selected profiles and original photo, and a
   later finding-chat request receives the same saved context.
7. Upload/analysis failures and manual retries preserve the same context and
   assessment identity. Reload/remote hydration does not erase the description.
8. The saved assessment shows the full read-only description after restart and
   reopening under the same account on another installation. Older records show
   the blank fallback. Account changes and deletion retain existing isolation and
   cleanup guarantees.
9. Preview preserves and displays the entered details locally while retaining its
   simulated-result disclosure and separation from account-backed data.
10. Verify narrow screens, enlarged text, multiline/long content, browser keyboard
    focus, native keyboard layout and platform back behavior. Storage errors must
    preserve input and must not produce a falsely saved state.

Use focused state/API-client tests for draft conversion, normalization, validation,
remote mapping and upload/retry input. Use frontend integration checks for the
capture/confirmation/saved-assessment flow, text-only drafts, persistence and error
recovery. Extend focused backend workflow/context tests where necessary to verify
that the existing field reaches initial analysis and finding chat. Run relevant
existing type/unit checks and record native checks that cannot be performed.

## Implementation references and verification of this spec

Read-only inspection identified these integration points:

- `mobile/app/capture.tsx`: profile section and current photo/profile-only dirty check.
- `mobile/app/confirm.tsx`: profile summary and edit navigation.
- `mobile/app/assessment/[id].tsx`: saved assessment presentation.
- `mobile/src/domain/model.ts`: `Draft`, `Assessment`, and `createAssessment`.
- `mobile/src/hooks/preview-context.tsx`: draft updates, persistence and retries.
- `mobile/src/storage/state-store.ts`: serialized durable state updates.
- `mobile/src/api/backend-client.ts`: `RemoteAssessment`, `fromServer`, multipart upload.
- `backend/app/api/routes.py`: optional `household_context`, maximum 3,000 characters.
- `backend/app/models/schemas.py`: persisted assessment context.
- `backend/app/assessments/service.py`: creation fingerprint and analysis context.
- `backend/app/assessments/chat.py`: saved household context and chat capacity checks.
- `backend/app/assessments/prompts/__init__.py`: existing safety/context treatment.

No conflict with ADR 0001's backend-owned Firestore persistence was identified.
The working tree already contains finding-chat implementation changes from an
earlier task; preserve that work. This specification did not change application
code, create implementation tickets, run runtime tests or commit changes.
