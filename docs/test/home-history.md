# Home, history and launch checks

Specification: [Home/history](../../.scratch/home-history/spec.md).

## Manual journeys

1. Cold-start the application. Check the house mark and Home Safety AI name while
   initialization runs, then existing authentication or Home, without a timed delay.
   Initialization failure must show a usable retry rather than a permanent splash.
2. Choose Assess a room, select a sample/photo and submit. Return Home, start a
   second assessment, then reopen the first from Previous assessments. Resolve,
   dismiss and reopen a finding; return Home and check the open count.
3. Restart the app on Home. Previous assessments should remain accessible. Sign
   into the same account on another installation and reopen an older assessment.
4. Leave a local draft and reopen Home. Check Resume assessment, and the
   Resume draft / Discard draft and start new / Cancel choices. Discarding the
   draft must retain all saved assessments and their photos.
5. In preview tools, use A closer look for a long title and No obvious hazards for
   a missing title. Home shows eight words plus … for the former and Room
   assessment for the latter, always with a date. Accessible row names use full titles.
6. With more than 20 saved server assessments, use Load more. Check chronological
   ordering, including matching creation times, and no duplicates. Disconnect
   during refresh/load-more: retain existing rows and retry the failed request.
7. Delete an assessment through its existing confirmation, then check Home. Sign
   out and sign into a different account: no prior account rows/photos may remain.
8. Check 320/430-pixel phone widths, larger windows, enlarged text, keyboard and
   screen-reader navigation, Android system back and iOS back gestures. Verify
   house-mark appearance under native launcher masks.

The native splash requires an installed release build for visual verification;
Expo Go and browser preview do not establish the final native appearance. See
[Expo's splash-screen guidance](https://docs.expo.dev/versions/latest/sdk/splash-screen/).
Native splash hands off to the same app-rendered house mark and name once its
first layout is available, so initialization errors remain visible and recoverable.

## Automated coverage

- `backend/tests/test_history.py`: title storage, legacy/blank titles, metadata
  counts, account isolation, tied-date pagination, deletion filtering, invalid
  cursors/limits, and no model calls during history reads.
- `mobile/tests/history.test.ts`: missing, blank, eight-word and longer titles.
- `mobile/tests/backend-client.test.ts`: authenticated history/photo references,
  cursor transport and opening an unfinished upload without running analysis.
- `mobile/tests/browser/home-history.spec.ts`: Home, draft choices, older checklist
  edits/restart, title presentation and small/large window screenshots.
- Existing preview and connected browser journeys now expect Home after deletion
  and explicitly select a history entry instead of relying on latest redirects.

## Verification record

Implementation checks run on 2026-11-01:

- Full backend and script suite: 127 passed, 7 opt-in checks skipped, 5 subtests passed.
- Full frontend unit/state/client suite: 20 passed.
- TypeScript and backend Ruff checks passed.
- Preview Home/history screenshots inspected at phone widths; automated overflow
  checks cover 320, 430 and 1280 pixels.
- Expo dependency check found the installed versions compatible using the local SDK
  dependency map; the online versions endpoint was unavailable in that check.

Storage-integrated and authenticated browser checks could not be completed:
`/usr/bin/docker` returns an input/output error, and a direct emulator adapter test
confirmed the photo-storage emulator at 127.0.0.1:4443 is unavailable. Native
device, actual launcher/splash, enlarged native text, and screen-reader checks
remain manual verification work. No live model calls were made.

The house-mark source is code in `scripts/generate-brand.py`; regenerate all
launcher/splash/favicon variants with
`backend/.venv/bin/python scripts/generate-brand.py`.
