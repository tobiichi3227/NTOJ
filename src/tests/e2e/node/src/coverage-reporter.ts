import type { Reporter } from "@playwright/test/reporter";
import { generateWebCoverageReport } from "./coverage";

export default class CoverageReporter implements Reporter {
  async onEnd(): Promise<void> {
    await generateWebCoverageReport();
  }
}
