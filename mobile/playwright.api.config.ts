import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./tests/api-browser",
  timeout: 60_000,
  expect: { timeout: 15_000 },
  workers: 1,
  fullyParallel: false,
  use: {
    baseURL: "http://127.0.0.1:8082",
    viewport: { width: 390, height: 844 },
    trace: "retain-on-failure",
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
      command: "npm run web -- --localhost --port 8082",
      env: {
        EXPO_PUBLIC_DATA_SOURCE: "api",
        EXPO_PUBLIC_API_URL: "http://127.0.0.1:8001",
        EXPO_PUBLIC_DEMO_TOKEN: "browser-integration-token",
      },
      url: "http://127.0.0.1:8082",
      timeout: 120_000,
      reuseExistingServer: false,
    },
  ],
});
