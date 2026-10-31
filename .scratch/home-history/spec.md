# Home, assessment history, and branded launch

## Purpose

Give Home Safety AI a stable entry point where users can start a room assessment,
resume their draft, and reopen previous assessments. Preserve the current visual
design and assessment workflow. Introduce a brief branded launch experience and
short model-generated titles to make saved assessments recognisable.

This spec records the proposal and the user's decisions from the grilling rounds.
It authorises specification work only; application implementation is a subsequent
task.

## Agreed scope

- Branded launch screen with an application icon and “Home Safety AI”.
- Home as the default destination after the existing authentication gate.
- A history list on Home, with older entries available through Load more.
- Existing assessment details and checklist actions available for older entries.
- One local draft, with an explicit resume/discard choice before replacing it.
- A title generated in the initial assessment model response, stored on the backend.
- Frontend title truncation and a fallback for records without titles.

No new tabs, separate history screen, onboarding, room-name input, search, filters,
room grouping, comparisons, title editing, or title backfill are needed.

## Design direction

Reading this as: a household safety companion with a calm, supportive interface,
targeting Android and iOS with browser preview support.

Use the mobile-design skill during implementation, particularly for the launch
screen and application icon. Dials: design variance 4/10, motion intensity 2/10,
visual density 4/10. Preserve existing typography, spacing, rounded surfaces,
finding cards, and these tokens from `mobile/src/components/theme.ts`:

| Role | Token/value |
| --- | --- |
| Background | `colors.background`, `#f7f6f1` |
| Brand accent | `colors.accent`, `#245c46` |
| Primary text | `colors.ink`, `#243d35` |
| Secondary text | `colors.muted`, `#56675e` |
| Soft surface | `colors.soft`, `#eaf0e7` |
| Card radius | `tokens.radius`, 18 |

### Launch screen and icon

- Replace stock Expo artwork with a simple, recognisable house symbol using the
  existing green-and-cream palette. Keep the launcher icon legible at small sizes;
  place the application name outside the symbol on the launch screen.
- Use one consistent house mark across the launcher, launch screen, and favicon.
  Produce the required platform variants, including Android adaptive/monochrome
  assets, from that design.
- Launch composition: full warm background, a centred house mark, and the name
  “Home Safety AI” beneath it. Generous whitespace; no promotional copy, buttons,
  decorative animation, or enforced minimum display duration.
- Show branding during actual initialization and transition as soon as ready.
  Preserve existing initialization errors and Retry controls rather than leaving
  the user behind a static launch screen.
- Use supported native splash behaviour and an app-rendered branded loading
  surface where necessary. Native platform restrictions may mean the OS splash
  displays the mark before the app-rendered name; match background and artwork
  to avoid a visible flash or a second timed splash.
- Browser preview uses the same branding during initialization. Authentication
  remains unchanged and appears when required after launch initialization.
- Returning from the background does not replay a timed launch experience.

## Navigation and Home

Normal launch: branded initialization → existing sign-in/verification if needed
→ Home. Returning signed-in users also arrive at Home, even with a saved draft or
an existing assessment. Preserve deliberate navigation to specific assessment
routes; do not force Home over every route transition.

Home content, in order:

1. Header identifying Home Safety AI, retaining access to the existing account UI.
2. Primary **Assess a room** button.
3. **Resume assessment** section when a local draft exists.
4. **Previous assessments** list, newest first.
5. **Load more** when another history page is available.

With no saved assessments, explain that previous room assessments will appear
here and keep Assess a room available. A loading or failed history request must
not be mistaken for an empty history.

Remove the current automatic redirects from Home to capture/latest assessment.
Reuse capture, confirmation, analysis, assessment, finding, and evidence screens.
Provide a visible way back Home from assessment and analysis screens. Back from
an entry opened through history returns to Home without replaying capture or
submission, preserving the loaded history and scroll position where possible.

## Draft behaviour

- Keep one account-local draft using existing persistence. Do not imply it is
  available on another device.
- Resume assessment opens that draft in the existing capture flow.
- Assess a room with no draft starts the existing creation flow.
- Assess a room with a draft opens a choice: **Resume draft** or **Discard draft
  and start new**, plus a non-destructive dismissal/cancel option.
- Discard removes only the draft. It does not delete saved assessments or photos.
- Dismissing the choice retains the draft. Prevent duplicate creation on repeated
  taps.

## History behaviour

Each row is tappable and contains:

- Initial photo thumbnail, with a neutral placeholder if unavailable.
- Assessment display title, using the rules below.
- Localised assessment creation date, always visible, including for fallback titles.
- Open finding count for completed analysis; appropriate progress state for an
  assessment still being analysed. Do not present an unfinished analysis as zero
  findings or a successful no-hazards result.
- A visible navigation affordance such as a chevron.

History includes retained assessments belonging to the signed-in account. Use
creation time descending and a stable ID tie-breaker; checklist changes do not
move entries to the top. Use cursor pagination (initial page of 20 records and
Load more) without duplicates. Exclude records undergoing deletion.

Opening a completed entry loads that assessment and enables the same existing
actions: view saved findings/evidence, resolve, dismiss, reopen, and open the
saved text-only finding chat. New follow-up/photo-review submissions are replaced
by chat; see `.scratch/finding-chat/spec.md`. Preserve existing deletion confirmation and retryable
backend deletion semantics. Update/remove the corresponding Home row after changes.

Opening an unfinished saved assessment uses its existing progress/recovery flow.
The user does not expect a separate collection of failed assessments; do not add
a failed-history category or filter. Preserve existing operational error/retry
handling if a saved assessment cannot complete. Merely listing or opening history
must not submit photos, start/restart model analysis, or create highlight attempts.

### History states

- Initial load: lightweight progress indication within Home; primary creation
  action remains available once the normal account/state prerequisites are ready.
- Empty: explanatory text and the primary action.
- Initial request error: inline explanation and Retry, distinct from empty.
- Load-more error: retain existing rows and allow retrying that page.
- Returning Home: reconcile metadata with changes made in the opened assessment.
- Refresh: provide an explicit refresh affordance, with pull-to-refresh optional.
- Missing/deleted selected record: explain it is unavailable and return to Home.
- Account change/sign-out: clear the prior account's history and draft view using
  existing account scoping. Never expose another account's records or photos.

## Assessment title contract

- Extend the initial assessment prompt and structured response with `title` for
  both supported providers through the shared model contract.
- Prompt for a neutral, descriptive title of **1–4 words**, based on the visible
  room or area, e.g. “Living Room Review” or “Kitchen Counter Review”. Avoid safety
  certification language such as “Safe Living Room”.
- Persist the full returned textual title with the assessment and expose it in
  assessment detail and history responses. Do not enforce a word-count rejection
  that discards an otherwise valid assessment merely because its title is long.
- Accept missing/blank titles through compatibility handling. Titles are plain
  text; existing schema/type and response-size safeguards still apply.
- Generate the title with the initial analysis, without a separate model request.
  Follow-ups, user-review evidence, and checklist status changes retain the title.
- No migration or model calls to generate titles for old records.

Frontend display rules:

1. Trim surrounding whitespace and treat whitespace-only text as missing.
2. Missing title: display **Room assessment**, with the creation date beneath it.
3. One through eight words: show the full title.
4. More than eight words: show the first eight words followed by `…`. Count words
   by whitespace after trimming; keep punctuation attached to its word.
5. Store the original title unchanged. Visual wrapping must accommodate narrow
   screens and larger text without obscuring the date or navigation affordance.
   Provide the full title in the row's accessible name.

## Backend and frontend integration

Current records are retained in Firestore, but only latest and get-by-ID are
exposed. Add an authenticated, account-scoped paginated history endpoint using
the existing repository/service/API boundaries. Proposed shape:

`GET /v1/assessments?limit=20&cursor=<opaque-cursor>`

Return lightweight items containing ID, optional title, creation time, analysis
state, open finding count when available, and the existing authenticated photo
reference, plus an optional next cursor. Do not embed full findings or image bytes
in every history row. Validate cursors and limits; preserve private photo access.

Load full assessment data on selection, including after app restart or on a new
installation. Existing mobile initialization keeps only the latest server record;
change history loading and route hydration accordingly. An uncached assessment
must load rather than immediately redirecting Home. Keep history metadata separate
from full assessment loading as needed, and preserve the existing latest endpoint
for compatibility.

Preview mode must support the same Home/history navigation using its separate
local sample state. It must not require credentials or backend calls. Include
sample titles and examples of missing and long titles for review.

## Accessibility and platform behaviour

- Respect safe areas, text scaling, and small phone/browser widths without
  horizontal scrolling. Preserve the current light visual theme.
- Minimum touch areas: 48 units for cross-platform controls; clear text labels,
  focus order, and accessible names for rows and draft choices.
- Use text alongside semantic status colours. Preserve contrast and existing
  reduced-motion behaviour; no launch animation is required.
- Browser supports keyboard navigation/focus. Android system back and iOS back
  behaviour return to the expected origin without losing saved state.

## Acceptance and verification

1. Cold launch displays the new branding with no artificial delay, then existing
   authentication or Home. Initialization errors remain recoverable.
2. Home remains reachable with an existing assessment or draft; no automatic
   redirect prevents browsing history or starting another assessment.
3. Starting with a draft offers Resume/Discard; cancel preserves input and discard
   leaves saved assessments untouched.
4. Create two assessments, restart, and reopen the older one from history. Its
   photos, findings, and checklist actions work. The same account on a fresh
   installation can browse its retained assessments.
5. History is account-scoped, ordered and paginated correctly. Refresh and returning
   from changes update rows. Deleted records disappear. Opening uncached IDs works.
6. The initial model response stores a title; subsequent evidence and status
   updates do not replace it. Older/missing/blank titles show Room assessment and
   their date. Exactly eight words display in full; nine or more show eight plus …,
   without altering stored text or rejecting otherwise valid analysis.
7. History browsing causes no model requests. Empty/loading/error/loading-more
   states are distinguishable and recoverable without losing already loaded rows.
8. Preview mode demonstrates Home and history independently of the backend.
9. Check narrow and large phone layouts, browser keyboard use, large text, screen
   reader labels, reduced motion, and native launch/back behaviour. Check icon
   appearance in launcher/adaptive masks. Native splash verification requires a
   suitable installed build; browser/Expo preview alone is insufficient.

Use focused backend contract tests for title compatibility, account isolation,
pagination and selected-record retrieval; frontend tests for draft choices, title
boundaries and history navigation. Run appropriate existing type, unit and browser
checks during implementation. Verify version-specific splash configuration against
the installed Expo version and current official documentation before implementing.

## Documentation and scope reconciliation

History intentionally expands the prior MVP scope. During implementation, update
the current scope statements in `CONTEXT.md`, `.scratch/authentication/spec.md`,
and `.scratch/frontend-preview/spec.md` to point to this feature rather than
claiming history remains excluded. No existing ADR forbids history. Preserve ADR
0001 storage/deletion semantics and ADRs 0002/0003 highlight behaviour.

## Verification of this specification

Inspected current navigation, authentication/draft behaviour, icon configuration,
title/model contracts, and backend history constraints through read-only codebase
review. No application code, branding assets, or tests have been changed or run
as part of specification authoring. Native launch appearance and the proposed
screens remain to be verified during implementation.
