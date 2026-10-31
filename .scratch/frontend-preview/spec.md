# Frontend preview

Decision state: agreed through user interview on 2026-10-27.
Requirements source: [`CONTEXT.md`](../../CONTEXT.md).
Implementation target: `mobile/`, Expo / React Native / TypeScript.

## Purpose

Build an interactive frontend so the user can review the pages and complete
product journey before backend and Muse integration. Use realistic, predefined
assessment results to verify that the product works with reasonable structured
output. This effort does not evaluate Muse's detection quality or accuracy.

The primary operator is an adult household member who usually takes care of
the family, assumed to have no disability. Maintain baseline accessibility;
household profiles describe the people or pets being considered, not the
operator's abilities.

Reading this as: a home-safety tool for an adult caring for their household,
with a calm, warm, readable interface, targeting Android first.

## Delivery boundary

- Deliver working navigation, real photo input, simulated analysis, finding
  actions, finding chat, and local restart persistence.
- Review in a browser and on an Android phone through Expo Go. Browser preview
  supports quick review; Android is the physical-device acceptance target.
- Show a clear preview label explaining that results are predefined and the
  selected photo is not being analysed. Do not imply that a model ran.
- Keep preview controls separate from the household-facing journey.
- No backend, cloud storage, API credentials, or Muse access is required.
- Preserve the eventual backend requirements in `CONTEXT.md`; local storage
  and fixtures are development substitutes, not changes to those decisions.

## Page flow

Start/resume → photo and household profiles → photo confirmation → analysis
progress → findings/checklist → finding detail → saved finding chat.

Use a stack with clear titles and back navigation. Do not add bottom tabs.
Home with assessment history is added by
[`home-history/spec.md`](../home-history/spec.md), superseding the start/resume and
latest-only navigation described below. Account flows remain a separate feature.

| Page | Content and actions | Required states |
| --- | --- | --- |
| Start/resume | Brief purpose, preview disclosure, begin an assessment; restore and open the latest assessment when one exists | First use, restoring saved state, storage failure |
| Photo and profiles | Camera, gallery/file selection, bundled sample photos; optional household profile selection | No photo, selected photo, cancelled picker, denied permission, unavailable camera, unreadable file |
| Photo confirmation | Inspect selected photo and profiles, replace photo, start assessment | Ready, invalid input, submission disabled or pending |
| Analysis progress | Honest simulated processing indication; prevent duplicate submissions | Pending, failure with retained input and Retry, success |
| Findings/checklist | Assessment photo, prioritised finding cards, completion progress, New assessment, secondary Delete assessment action | Findings present, no obvious visible hazards, partially complete, all items handled |
| Finding detail | Severity, visible evidence, uncertainty, full recommendation, status and related evidence | Open, resolved, dismissed; chat empty, pending, completed or failed; historical evidence viewable |
| Finding chat | Saved text-only discussion, multiline composer and Send | Empty, loading, pending, failed with manual retry, complete, invalid input and limit |
| User-requested review | New photo linked to the finding, simulated check, user decision after feedback | Photo input, pending, failure preserving existing finding, review feedback |

Follow-up and review may share presentation components, but must preserve their
different intent and the finding to which they belong. Confirmation dialogs are
required for assessment deletion and abandoning an unfinished photo submission.
Back and cancellation must return to a sensible prior screen without submitting.

## Household profiles

Show optional multi-select choices: **Older adult**, **Child**, **Baby**, **Pet**.
Selecting none means a general assessment; do not add a mutually exclusive
General profile or require a choice. Show the selected profiles on confirmation
and retain them with their assessment.

**Baby** is the agreed user-facing name for the infant profile described in
`CONTEXT.md`. This copy change does not settle a future API field name or alter
the domain definition. Do not expose “Infant” as the profile label in the UI.

## Photo input

- Support Android camera and gallery input, browser file selection, and bundled
  room photos for repeatable review.
- Use camera capture in a browser only when supported. Keep file selection and
  samples available as fallbacks.
- Request permission when the related action is taken, explain its purpose,
  and offer another input path after denial. A cancelled picker is not an error.
- Show the chosen image before submission and allow replacement.
- Retain initial, follow-up, and review photos with the local assessment. Copy
  Android temporary selections into app-owned persistent storage as needed;
  retain browser uploads in durable browser storage rather than relying on
  temporary object URLs across reloads.
- Missing or unreadable photos require an explicit recovery path. Do not
  silently replace a user's selected photo with a sample.

## Findings and checklist behavior

- Use realistic fixture content with stable assessment and finding identifiers.
  Each finding includes category, severity, evidence, recommendation,
  uncertainty, and status. Fixtures are not a final backend contract.
- Show compact cards containing a title, severity label, short recommended
  action, status, and visible completion control. Severity must be conveyed in
  text as well as color. Prioritise higher-severity open findings.
- Exactly one completable checklist item corresponds to each finding. Cards
  and detail screens operate on the same status, with no separate checklist
  state that can disagree.
- Support `open`, `resolved`, and `dismissed`. Only the user marks an item
  resolved. Dismissal accepts an optional note; resolved and dismissed findings
  can be reopened.
- Detail exposes the complete evidence, uncertainty, recommendation, and
  Chat about it for every status. Keep destructive actions secondary.
- Completion summaries distinguish resolved from dismissed items. Handling all
  findings does not certify that the room is safe.

## Finding chat behavior

- See `.scratch/finding-chat/spec.md` for the current conversation contract.
- Chat about it replaces the closer-look panel and Ask AI to check for every finding.
- Opening chat reads history without generating an answer. Questions and replies are
  advisory and never change findings, revisions, annotations or checklist status.
- Preview uses local sample history and simulated replies, separate from account data.
- Preserve local unsent drafts on back/restart, and preserve a new draft while
  explicitly retrying a failed saved question. Do not duplicate messages on retry.
- Keep completed historical evidence and photos viewable; stale evidence routes return
  to the finding without offering new follow-up/photo-review submissions.

## Assessment lifecycle and persistence

- Persist the latest assessment, profile selections, evidence, findings,
  dismissal notes, follow-up state, and review state across reloads/restarts.
- Restore assessment state and open Home with history. If analysis
  was interrupted, present a recoverable state with manual retry; do not invent
  successful results or spin indefinitely.
- Starting a new assessment retains earlier assessments and their photos. It
  does not delete or overwrite the last completed assessment when a new draft
  is cancelled. Earlier assessments can be opened from Home history.
- Confirm before abandoning an unfinished photo submission.
- Confirm Delete assessment, then remove its locally retained record and all
  associated photos. Return to Home, retaining the remaining history or showing
  its empty state when none remain.
- Provide an explicit development-only reset to clear preview data. Keep it
  separate from deleting a single assessment.
- Surface storage/write failures rather than implying changes were saved.

## Preview data and failure states

Provide a development-only scenario selector with repeatable fixtures for:

1. Visible hazards with actionable findings and mixed severities.
2. An uncertain finding with text-only advisory chat and explicit uncertainty.
3. No obvious visible hazards, with qualified language rather than a safety claim.
4. Analysis failure followed by successful manual retry.
5. Follow-up or review failure that preserves prior findings and submitted input.

Permission denial and unsupported photo capture must also have usable product
states. Simulated states may support repeatable review where reproducing the
real OS condition is impractical. Scenario selection must not silently reset an
existing assessment; use a fresh demo or explicit reset.

These scenarios verify UI behavior and recovery with reasonable output. They
are not an evaluation dataset, model accuracy claims, or a separate eval framework.
Do not spend this effort on speculative malformed-model-output combinations;
server validation belongs to later backend integration.

## Visual and interaction requirements

- Warm neutral surfaces, restrained green brand accent, system typography,
  generous but purposeful spacing, and clearly differentiated semantic colors.
- Design dials: variance **4/10**, motion **2/10**, density **3/10**.
- Deliver a polished light theme first. Dark theme and iOS-specific polish are
  deferred; preserve readable system controls when the device uses dark mode.
- Avoid centered website-style hero screens, decorative gradients, excessive
  nested cards, and decorative motion. Prioritise the photo and next action.
- Establish reusable tokens for surface, text, accent, severity, spacing, type,
  radius, and interaction states; apply them consistently across pages.
- Design loading, empty, error, disabled, pressed, and success states. Pending
  feedback must not claim a successful assessment before results exist.
- Use at least 48dp Android touch targets, accessible names/roles/states, logical
  screen-reader focus, scalable text, and visible alternatives to gestures.
- Meet WCAG AA contrast: 4.5:1 body text and 3:1 large text/UI components.
- Handle Android system bars, safe areas, system back, keyboard overlap, and
  scrolling with large text. Destructive actions require deliberate confirmation.
- Respect reduced-motion preferences. Prefer native transitions and simple
  progress feedback over elaborate animations or unnecessary haptics.
- Adapt to narrow and wide phone windows. Desktop browser review should use a
  comfortable constrained content width rather than stretched phone layouts.
- English is the initial language. Allow longer labels and text wrapping without
  clipping; translation and RTL implementation are outside this effort.

## Safety and trust copy

Display the required disclaimer where users start an assessment and review its
results, with consistent wording:

> AI-generated suggestions based on visible information only; not a professional home safety inspection.

Also show a distinct preview disclosure wherever simulated results could be
mistaken for analysis of the selected photo. Use cautious finding language and
explicit uncertainty. No-hazards and all-complete states must not declare the
room safe. Fixture recommendations must avoid dangerous work; urgent examples
should direct users toward appropriate emergency or professional assistance.

## Implementation guidance and tooling

- Use the repository's `mobile-design` skill for visual hierarchy, Android
  conventions, accessibility, state completeness, and review.
- Use the installed `expo@openai-curated` plugin's relevant skills, including
  `building-native-ui`, for Expo implementation guidance. It is locally installed
  and enabled; no Expo MCP tools are exposed in this session.
- Use Expo Router stack navigation. The current starter uses `App.tsx` without a
  router; migration, entry configuration, and a working root route are part of
  implementation. Keep routes in `mobile/app/`, with shared UI and logic in
  `mobile/src/`. Remove obsolete entry wiring when replacing it.
- Keep Android-first requirements authoritative where Expo guidance is oriented
  toward Apple conventions. Do not use iOS-only symbols or effects without
  Android/browser equivalents.
- Try Expo Go first. Verify required packages against the installed Expo SDK and
  current official documentation; do not assume every module works in Expo Go.
- Isolate fixture operations behind a small service interface so later FastAPI
  integration can replace them without rewriting screens. Keep input handling,
  domain state, persistence, and visual components distinct where useful.
- Do not settle model endpoints, credentials, or API contracts in this effort.
  Muse remains the only permitted eventual model; there is no fallback model.
- No credentials belong in the frontend or client-exposed environment variables.

## Acceptance and review

The implementation is ready for page review when all of the following can be
demonstrated:

1. From a clean start, an adult user can identify the purpose and next action
   within five seconds, select a sample or actual photo, choose several profiles
   including **Baby**, confirm, and reach clearly labelled simulated findings.
2. A reviewer can inspect every page and relevant state in the agreed flow using
   the development scenarios, without a backend or Muse credentials.
3. Camera/gallery works on Android; browser file selection works, with samples
   and permission/capture fallbacks available.
4. Finding cards and detail agree on status. Resolve, dismiss with optional note,
   and reopen work; checklist counts remain consistent with findings.
5. Every finding opens its own saved text-only chat. Simulated replies never
   revise evidence or change finding status. Removed evidence controls stay absent.
6. Initial-analysis and linked-update failures offer manual retry with retained
   input. Linked failures preserve findings; repeat taps/retry create no duplicates.
7. Restart/reload restores the latest assessment, its photos, and its user actions.
   New assessment retains earlier data; cancelling its draft preserves the prior
   assessment; confirmed deletion removes the selected assessment and its photos.
8. No-hazards and all-handled results avoid safety certification. Preview and
   safety disclosures remain clear and readable.
9. Review small and large phone widths, desktop browser, enlarged text, keyboard
   open, system back, permission denial, and destructive confirmation. Primary
   actions remain visible or reachable, labelled, and usable.
10. TypeScript checking, Expo dependency compatibility, and web/Android bundling
    pass. Run the journey in browser and Android Expo Go; record which physical
    checks actually ran and any unavailable checks rather than claiming success.

Capture manual demo checks and observed limitations in `docs/demo.md` when
implemented. Use focused automated tests for meaningful state and persistence
behavior where useful, without duplicating trivial UI implementation details.

## Out of scope

Real Muse analysis or accuracy evaluation; FastAPI/VM integration; final API
schemas; authentication or accounts; cross-device sync; assessment comparison
screens; photo annotations; illustrative redesign; shopping or
booking; dark theme; iOS acceptance; custom native builds unless a verified
requirement makes Expo Go insufficient.

## Decisions recorded

- User chose a clickable end-to-end frontend with simulated results.
- Primary operator is an adult household member caring for the family.
- Warm, calm visual direction and browser plus Android review were agreed.
- Real photo input plus samples, development scenarios, local persistence,
  compact finding cards, and the proposed page flow were agreed.
- User clarified that this effort concerns product behavior with reasonable
  output, not control over Muse's output quality.
- Assessment lifecycle, Expo Router, light-first delivery, and the implementation
  boundary were confirmed. User-facing **Infant** was renamed **Baby**.
