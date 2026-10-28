# Frontend checks

Complete the [development setup](../../README.md#development-environment) first.

From `mobile/`:

```bash
npm run typecheck
npm test
```

Install the test browser once, then run the browser journeys:

```bash
npx playwright install chromium
npm run test:e2e
# Requires backend dependencies and running storage emulators; no model calls:
npm run test:e2e:api
```

The preview browser runner starts its own Expo server on port 8083. The API
suite starts a deterministic model fixture on 8001 and Expo on 8082, using real
storage emulators on 8080 and 4443. Screenshots and test artifacts are written
to the ignored `.tools/` directory. Neither suite calls Muse or Groq.

Check Expo compatibility and build both targets without an Android SDK:

```bash
npx expo install --check
npx expo-doctor
npx expo export --platform web --platform android
```

Use `npm run format` to format the frontend source and tests.
