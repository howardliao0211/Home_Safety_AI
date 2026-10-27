# Frontend preview checks

Implemented against `.scratch/frontend-preview/spec.md` on 2026-10-27.
This is a frontend demonstration with predefined results. No Muse analysis,
model accuracy evaluation, backend, or cloud persistence was exercised.

## Run the review

```bash
source scripts/frontend-env.sh
cd mobile
npm run web
```

Open the printed localhost URL. On first use, choose **Start with a room**.
Use a camera/gallery photo or a bundled sample, select optional profiles
(including **Baby**), confirm, and create a sample assessment.

**Preview** in the development header selects a scenario for the next fresh
demo. It does not change existing assessments. Start a fresh demo to inspect
uncertainty, no obvious hazards, analysis retry, linked-update retry, or camera
permission denial. A current draft requires confirmation before replacement.

For Android, run `npm start` and scan the QR code with SDK-compatible Expo Go.
Use `npm run start:tunnel` if WSL/LAN networking prevents phone access.

## Automated verification performed

- TypeScript checking passed.
- Seven state/service tests passed: serialized durable writes, rollback after
  storage failure, interrupted-operation recovery, preservation of user status,
  linked-update identity, photo retention, counts, and explicit analysis retry.
- Fourteen Chromium browser journeys passed, covering:
  - Multiple profiles, resolve/dismiss/reopen, notes, and restart persistence.
  - Text clarification and photo review without automatic resolution.
  - Skipping an agent follow-up while retaining user-requested review.
  - Failed analysis and linked updates, retained input, and manual retry.
  - Actual browser file upload persisted as image data across reload.
  - Draft cancellation, confirmation, assessment deletion, and restoration of
    the latest remaining assessment.
  - Qualified no-hazards and all-items-handled states.
  - Simulated camera denial with alternate input.
  - Injected IndexedDB quota failure without falsely saved status changes.
  - Reload during processing followed by explicit interrupted-state retry.
  - Preserving an edited text answer before back navigation.
  - Confirmed reset of assessments and unfinished draft data.
  - Layouts at 320px, 430px, and 1280px with no document horizontal overflow.
- Expo dependency compatibility passed; Expo Doctor passed all 21 checks after
  aligning the native font and animation dependencies to SDK 57.
- Web and Android exports passed. A normal browser journey produced no browser
  console errors or warnings in a separate runtime check.

Screenshots were inspected at phone widths. The first action is visible without
scrolling through the introduction; results show the next actions, readable
severity labels, and explicit preview status. Screenshots and test failure
artifacts are saved in ignored `.tools/screenshots/` and `.tools/browser-results/`.

## Physical-device and manual checks still needed

This environment has no attached Android device, adb, or configured emulator.
An Android bundle is not proof that device behavior works. Complete these in
Expo Go before accepting the physical-device demo:

- Real camera and gallery capture; cancellation; actual permission denial and
  device-settings recovery; camera activity interruption.
- Restart with initial, follow-up, and review photos, then confirmed deletion
  and verification that associated app-owned photo files are removed.
- Android system back, gesture navigation, landscape, keyboard overlap, and
  safe areas with both gesture and three-button navigation.
- Largest system font/display sizes, TalkBack focus and state announcements,
  reduced-motion preference, and dark system appearance with the light app theme.
- Browser keyboard focus through dialogs and file selection on target browsers.
  Browser camera availability depends on device/browser support; file upload
  and bundled samples are the supported fallback.

## Limitations

- Fixture descriptions do not establish hazards in the selected or bundled room
  photos. Preview disclosure is intentional and must stay visible.
- Data is local to this browser origin or app installation. Clearing browser/app
  data removes it. Local records do not implement the eventual VM persistence
  or device-scoped API contract.
- Earlier assessments are retained but have no history browser. Deleting the
  latest one restores the latest remaining record.
- Browser image selections use IndexedDB; native image copies use the app's
  document directory. Storage failures remain visible and do not publish a
  falsely saved action. Failed photo cleanup offers an explicit retry.
- Large browser uploads are limited to 15 MB for this preview.
- Eight npm dependency advisories remain (three high, five moderate), involving
  Expo CLI/Zod, Router URL parsing, and tunnel support. No forced major SDK
  downgrade or unverified dependency override was applied.
- iOS, dark theme, live backend/Muse integration, history, and annotations are
  outside this implementation.

## Reproduce automated checks

From `mobile/`:

```bash
npm run typecheck
npm test
npx playwright install chromium
npm run test:e2e
npx expo install --check
npx expo-doctor
npx expo export --platform web --platform android
```

The browser runner starts or reuses a localhost Expo server on port 8081.
Use `npm run format` to format frontend source and tests.
