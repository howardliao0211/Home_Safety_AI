import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./tests/browser",
  timeout: 45_000,
  expect: { timeout: 12_000 },
  fullyParallel: false,
  workers: 1,
  use: {
    baseURL: "http://localhost:8083",
    viewport: { width: 390, height: 844 },
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    reducedMotion: "reduce",
  },
  outputDir: "../.tools/browser-results",
  webServer: {
    command: "npm run web -- --localhost --port 8083",
    env: { EXPO_PUBLIC_DATA_SOURCE: "preview" },
    url: "http://localhost:8083",
    reuseExistingServer: false,
    timeout: 120_000,
  },
});
