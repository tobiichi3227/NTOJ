import { defineConfig, devices } from "@playwright/test";
import { existsSync } from "node:fs";

if (
  (process.env.NTOJ_E2E_WEB_COVERAGE === "1" || existsSync(".coverage-workflow-active")) &&
  process.env.NTOJ_E2E_COVERAGE_OWNER !== "run-coverage"
) {
  throw new Error(
    "Playwright is isolated by the active src/tests/e2e/run-coverage.sh workflow",
  );
}

const baseURL = process.env.NTOJ_E2E_BASE_URL ?? "http://127.0.0.1:5502";
const outputDir = process.env.NTOJ_E2E_OUTPUT_DIR ?? "test-results";
const htmlReportDir =
  process.env.NTOJ_E2E_HTML_REPORT_DIR ?? "playwright-report";

export default defineConfig({
  globalSetup: "./src/coverage-global-setup.ts",
  testDir: "./tests",
  fullyParallel: false,
  workers: 1,
  timeout: 30_000,
  expect: {
    timeout: 5_000,
  },
  outputDir,
  reporter: [
    ["list"],
    ["html", { outputFolder: htmlReportDir, open: "never" }],
    ["./src/coverage-reporter.ts"],
  ],
  use: {
    ...devices["Desktop Chrome"],
    baseURL,
    locale: "zh-TW",
    timezoneId: "Asia/Taipei",
    viewport: { width: 1440, height: 1000 },
    trace: "on",
    screenshot: "on",
    video: "on",
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],
});
