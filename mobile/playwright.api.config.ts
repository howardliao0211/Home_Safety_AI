import { defineConfig } from "@playwright/test";

// Override when another Expo server already uses the default port.
const port = process.env.API_TEST_FRONTEND_PORT ?? "8082";

export default defineConfig({
  testDir: "./tests/api-browser",
  timeout: 60_000,
  expect: { timeout: 15_000 },
  workers: 1,
  fullyParallel: false,
  use: {
    baseURL: `http://127.0.0.1:${port}`,
    viewport: { width: 390, height: 844 },
    trace: "off",
    screenshot: "only-on-failure",
    reducedMotion: "reduce",
  },
  outputDir: "../.tools/api-browser-results",
  webServer: [
    {
      command: "../backend/.venv/bin/python ../backend/tests/api_server.py",
      url: "http://127.0.0.1:8001/__test/ready",
      timeout: 60_000,
      reuseExistingServer: false,
    },
    {
      command: `npm run web -- --localhost --port ${port}`,
      env: {
        EXPO_PUBLIC_DATA_SOURCE: "api",
        EXPO_PUBLIC_API_URL: "http://127.0.0.1:8001",
        EXPO_PUBLIC_AUTH_EMULATOR_URL: "http://127.0.0.1:9099",
        EXPO_PUBLIC_FIREBASE_PROJECT_ID: "home-safety-local",
      },
      url: `http://127.0.0.1:${port}`,
      timeout: 120_000,
      reuseExistingServer: false,
    },
  ],
});
