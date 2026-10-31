# Mobile UI final review handoff

Date: 2026-11-01

## Purpose and authorization

The user requested a final UI component check using `mobile-design`, then requested this handoff under `.scratch/handoff`. The review is complete; three findings remain unresolved. No UI implementation changes were requested or made. A next session can use this document to discuss or implement the findings when authorized.

This document uses repository-root-relative paths. The working app is `mobile/`. The handoff skill normally requests OS temporary storage; the user's explicit destination overrides that default.

## Read first

- `AGENTS.md` and `docs/agents/domain.md` for repository instructions.
- `CONTEXT.md` for the product vocabulary, platform priorities, and boundaries.
- `docs/agents/issue-tracker.md` before creating or modifying specs/issues.
- `mobile/package.json`, `mobile/app.json`, and `mobile/playwright.config.ts` for the actual stack, platform configuration, and test setup. Do not copy package versions from this handoff; inspect the files.

## Review frame

Reading this as a home safety assistant for households reviewing potential hazards, with a calm, restrained interface, targeting Android first and iOS, with web preview support.

Chosen dials: design variance 3/10, motion 2/10, visual density 4/10. Preserve the existing brand tokens in `mobile/src/components/theme.ts`. The app explicitly uses light mode. Home and checklist screens passed the qualitative five-second comprehension and obvious-action checks at normal text size.

## Unresolved findings

### [P1] MD-003: Dialog actions become unreachable at larger text sizes

Locations at review time:

- `mobile/src/components/ui.tsx:360` (`ConfirmDialog`).
- `mobile/src/components/ui.tsx:440` (shared backdrop/dialog styles).
- `mobile/src/components/new-assessment-button.tsx:37` (draft chooser shares these styles).

The dialog is vertically centered without a viewport height constraint or scrolling. Browser reproduction at 320×640 with 200% simulated text size produced a 1026px-tall confirmation dialog starting at y=-193; the cancel button started at y=703, beyond the viewport. Normal-size deletion dialogs fit at 390×844 and 844×390.

Required direction: constrain dialog height to available safe-area space and provide scrolling so both destructive and cancel actions remain reachable. Check both confirmation and draft-choice dialogs. Browser text scaling was simulated by doubling computed font sizes and line heights, not by native Dynamic Type; verify native behavior separately.

### [P1] MD-007: Shared notices lack an iOS announcement path

Location: `mobile/src/components/ui.tsx:165` (`Notice`).

Shared notices rely on `accessibilityLiveRegion="polite"`, which is Android-only. New errors and results can appear without an iOS VoiceOver announcement. This is a source-level finding, not a native screen-reader reproduction.

Required direction: provide an iOS announcement path for meaningful new notice/error content, avoid duplicate announcements, and preserve interactive children. Existing iOS announcement examples are in `mobile/src/components/room-concept.tsx`, `mobile/app/chat/[assessmentId]/[findingId].tsx`, and `mobile/src/auth/screen.tsx`.

Official reference checked: https://reactnative.dev/docs/accessibility#accessibilityliveregion-android

### [P2] MD-004: Deletion errors are hidden behind the open confirmation

Locations:

- `mobile/app/assessment/[id].tsx:188` (confirmation callback).
- `mobile/src/hooks/preview-context.tsx` (`act` and `deleteAssessment`).
- `mobile/src/components/ui.tsx` (`Screen` renders the global error notice).

Reproduced in isolated browser preview data by making `IDBObjectStore.prototype.put` throw a `QuotaExceededError`, then confirming deletion. The dialog stayed open; the error appeared outside and behind it, with no error inside the dialog. The callback closes the dialog only on success.

Required direction: show failure and retry feedback inside the active confirmation dialog, preserving a usable cancel path. Consider other async actions that use the same dialog pattern.

## Verification completed

- `npm run typecheck`: passed.
- Three existing tests from `mobile/tests/browser/journey.spec.ts`: all passed (15.5 seconds total):
  - Household journey: profiles, checklist actions, dismissal, persistence, and finding chat.
  - New draft cancellation, retained earlier assessment, and deletion returning Home.
  - Camera denial with alternate photo input and a usable next step.
- Browser screenshots inspected for Home, checklist, and enlarged-text deletion dialog.
- Sampled token contrast ratios passed AA for normal text: ink/background 10.82, muted/background 5.55, accent/surface 7.79, danger/dangerSoft 6.37, amber/amberSoft 6.02.
- Native screen readers, actual Dynamic Type, native keyboard/insets, RTL/localization, and on-device runtime behavior were not verified. No full end-to-end suite or production backend checks were run.

## Local reproduction artifacts

Temporary artifacts may disappear between sessions; they are supplementary, not required inputs:

- `/tmp/mobile-ui-review/check.cjs`: browser layout reproduction.
- `/tmp/mobile-ui-review/recovery.cjs`: failed-deletion reproduction.
- `/tmp/mobile-ui-review/playwright.config.cjs`: test configuration targeting the already-running preview server, with output under `/tmp`.
- `/tmp/mobile-ui-review/`: screenshots including `home.png`, `checklist.png`, `dialog-scaled.png`, and `delete-failure.png`, plus test results.

The preview was started from `mobile/` with `EXPO_PUBLIC_DATA_SOURCE=preview npm run web -- --localhost --port 8084`. The review's port-8084 server was stopped afterward. Port 8083 was already occupied; do not stop an unrelated process.

Chromium needed the existing local libraries: `LD_LIBRARY_PATH=/tmp/home-safety-browser-libs/usr/lib/x86_64-linux-gnu`. The default browser launch initially failed on missing `libnspr4.so`. Local server/browser execution needed sandbox escalation. No system packages were installed.

During immediate modal inspection, web accessibility queries briefly found nested dialog roles. The existing deletion journey later passed unchanged, so this was not reported as a confirmed product defect.

## Workspace preservation

The following changes predated the review and were left untouched:

- Modified: `mobile/app.json`, `mobile/package.json`.
- Untracked: `mobile/BUILDING.md`, `mobile/eas.json`.

Inspect current status before making changes and preserve the user's build-related work. No UI files were edited, no dependencies were changed, and no commits were created during the review.

## Suggested skills

Ask the next agent to invoke these through the Skill tool if available, or read their installed `SKILL.md` according to the environment's skill-loading instructions:

- `mobile-design`: recheck the findings and guide platform-aware fixes and verification. Its project skill file is `.codex/skills/mobile-design/SKILL.md`.
- `mattpocock-skills:diagnosing-bugs`: use if implementing the reproduced dialog overflow or hidden error behavior; follow its diagnosis loop.
- `mattpocock-skills:tdd`: use if the next task explicitly requests test-first fixes or integration tests.

After any authorized fixes, run focused checks covering reachable dialog actions at large text/short heights, visible failure recovery, and announcement behavior. Broaden testing only if changes or unresolved failures warrant it.
