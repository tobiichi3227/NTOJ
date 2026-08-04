import { resetWebCoverage, WEB_COVERAGE_ENABLED } from "./coverage";

export default async function globalSetup(): Promise<void> {
  if (
    WEB_COVERAGE_ENABLED &&
    process.env.NTOJ_E2E_COVERAGE_OWNER !== "run-coverage"
  ) {
    throw new Error(
      "Browser coverage can only be started through src/tests/e2e/run-coverage.sh",
    );
  }
  await resetWebCoverage();
}
