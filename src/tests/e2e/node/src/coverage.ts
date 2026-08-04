import { createHash } from "node:crypto";
import { mkdir, readFile, readdir, writeFile } from "node:fs/promises";
import * as path from "node:path";
import { BrowserContext, Page, TestInfo } from "@playwright/test";
import {
  sourceCoverageKey,
  writeSourceCoverageReports,
} from "./coverage-source-report";

export const WEB_COVERAGE_ENABLED =
  process.env.NTOJ_E2E_WEB_COVERAGE === "1";

const coverageRoot = path.resolve(
  process.env.NTOJ_E2E_WEB_COVERAGE_DIR ?? "coverage/web",
);
const rawCoverageDirectory = path.join(coverageRoot, "raw");

type JsCoverageEntry = Awaited<
  ReturnType<Page["coverage"]["stopJSCoverage"]>
>[number];
type CssCoverageEntry = Awaited<
  ReturnType<Page["coverage"]["stopCSSCoverage"]>
>[number];

type RawCoverage = {
  testId: string;
  title: string;
  js: JsCoverageEntry[];
  css: CssCoverageEntry[];
};

type ByteRange = {
  start: number;
  end: number;
};

type ResourceCoverage = {
  kind: "JavaScript" | "CSS";
  url: string;
  sourceHash: string;
  source: string;
  totalBytes: number;
  coveredRanges: ByteRange[];
};

export class BrowserCoverageSession {
  private readonly origin: string;
  private readonly pages = new Map<Page, Promise<void>>();
  private readonly finishedContexts = new WeakSet<BrowserContext>();
  private readonly js: JsCoverageEntry[] = [];
  private readonly css: CssCoverageEntry[] = [];

  constructor(
    baseURL: string,
    private readonly testInfo: TestInfo,
  ) {
    this.origin = new URL(baseURL).origin;
  }

  async trackContext(context: BrowserContext): Promise<void> {
    if (!WEB_COVERAGE_ENABLED) return;
    context.on("page", (page) => {
      void this.trackPage(page);
    });
    await Promise.all(context.pages().map((page) => this.trackPage(page)));
  }

  async finishContext(context: BrowserContext): Promise<void> {
    if (!WEB_COVERAGE_ENABLED || this.finishedContexts.has(context)) return;
    this.finishedContexts.add(context);

    for (const page of context.pages()) {
      const started = this.pages.get(page);
      if (!started || page.isClosed()) continue;
      await started;
      const [js, css] = await Promise.all([
        page.coverage.stopJSCoverage(),
        page.coverage.stopCSSCoverage(),
      ]);
      this.js.push(...js.filter((entry) => this.isApplicationUrl(entry.url)));
      this.css.push(...css.filter((entry) => this.isApplicationUrl(entry.url)));
    }
  }

  async writeRawCoverage(): Promise<void> {
    if (!WEB_COVERAGE_ENABLED) return;
    await mkdir(rawCoverageDirectory, { recursive: true });
    const id = createHash("sha1")
      .update(`${this.testInfo.testId}:${this.testInfo.retry}`)
      .digest("hex")
      .slice(0, 16);
    const report: RawCoverage = {
      testId: this.testInfo.testId,
      title: this.testInfo.titlePath.join(" > "),
      js: this.js,
      css: this.css,
    };
    await writeFile(
      path.join(rawCoverageDirectory, `${this.testInfo.workerIndex}-${id}.json`),
      JSON.stringify(report),
    );
  }

  private async trackPage(page: Page): Promise<void> {
    const existing = this.pages.get(page);
    if (existing) return existing;
    const started = Promise.all([
      page.coverage.startJSCoverage({ resetOnNavigation: false }),
      page.coverage.startCSSCoverage({ resetOnNavigation: false }),
    ]).then(() => undefined);
    this.pages.set(page, started);
    await started;
  }

  private isApplicationUrl(value: string): boolean {
    if (!value) return false;
    try {
      const url = new URL(value);
      return (
        url.origin === this.origin &&
        !url.pathname.startsWith("/static/third/") &&
        !url.pathname.startsWith("/src/third/")
      );
    } catch {
      return false;
    }
  }
}

function clampRange(range: ByteRange, totalBytes: number): ByteRange | null {
  const start = Math.max(0, Math.min(totalBytes, range.start));
  const end = Math.max(start, Math.min(totalBytes, range.end));
  return end > start ? { start, end } : null;
}

function mergeRanges(ranges: ByteRange[], totalBytes: number): ByteRange[] {
  const sorted = ranges
    .map((range) => clampRange(range, totalBytes))
    .filter((range): range is ByteRange => range !== null)
    .sort((left, right) => left.start - right.start || left.end - right.end);
  const merged: ByteRange[] = [];
  for (const range of sorted) {
    const previous = merged.at(-1);
    if (!previous || range.start > previous.end) {
      merged.push({ ...range });
    } else {
      previous.end = Math.max(previous.end, range.end);
    }
  }
  return merged;
}

function jsCoveredRanges(entry: JsCoverageEntry): ByteRange[] {
  const totalBytes = entry.source?.length ?? 0;
  const ranges = entry.functions.flatMap((func) => func.ranges);
  const boundaries = [...new Set(ranges.flatMap((range) => [
    Math.max(0, Math.min(totalBytes, range.startOffset)),
    Math.max(0, Math.min(totalBytes, range.endOffset)),
  ]))].sort((left, right) => left - right);
  const covered: ByteRange[] = [];

  for (let index = 0; index < boundaries.length - 1; index += 1) {
    const start = boundaries[index];
    const end = boundaries[index + 1];
    if (end <= start) continue;
    const applicable = ranges
      .filter((range) => range.startOffset <= start && range.endOffset >= end)
      .sort(
        (left, right) =>
          left.endOffset - left.startOffset - (right.endOffset - right.startOffset),
      );
    if (applicable[0]?.count > 0) covered.push({ start, end });
  }
  return mergeRanges(covered, totalBytes);
}

function coveredBytes(ranges: ByteRange[]): number {
  return ranges.reduce((total, range) => total + range.end - range.start, 0);
}

function percent(covered: number, total: number): number {
  return total === 0 ? 100 : Number(((covered / total) * 100).toFixed(2));
}

function escapeHtml(value: string): string {
  return value
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

export async function resetWebCoverage(): Promise<void> {
  if (!WEB_COVERAGE_ENABLED) return;
  const { rm } = await import("node:fs/promises");
  await rm(coverageRoot, { recursive: true, force: true });
  await mkdir(rawCoverageDirectory, { recursive: true });
}

export async function generateWebCoverageReport(): Promise<void> {
  if (!WEB_COVERAGE_ENABLED) return;
  await mkdir(coverageRoot, { recursive: true });
  const resources = new Map<string, ResourceCoverage>();
  let rawFiles: string[] = [];
  try {
    rawFiles = (await readdir(rawCoverageDirectory)).filter((file) =>
      file.endsWith(".json"),
    );
  } catch {
    rawFiles = [];
  }

  for (const file of rawFiles) {
    const raw = JSON.parse(
      await readFile(path.join(rawCoverageDirectory, file), "utf8"),
    ) as RawCoverage;
    for (const entry of raw.js) {
      if (!entry.source) continue;
      addResource(
        resources,
        "JavaScript",
        entry.url,
        entry.source,
        jsCoveredRanges(entry),
      );
    }
    for (const entry of raw.css) {
      if (!entry.text) continue;
      addResource(
        resources,
        "CSS",
        entry.url,
        entry.text,
        entry.ranges.map((range) => ({ start: range.start, end: range.end })),
      );
    }
  }

  const sourceReports = await writeSourceCoverageReports(
    coverageRoot,
    [...resources.values()],
  );
  const rows = [...resources.values()]
    .map((resource) => {
      const covered = coveredBytes(resource.coveredRanges);
      const detail = sourceReports.get(sourceCoverageKey(resource));
      return {
        kind: resource.kind,
        url: resource.url,
        sourceHash: resource.sourceHash,
        detailPath: detail?.detailPath ?? "",
        displayName: detail?.displayName ?? new URL(resource.url).pathname,
        sourceType: detail?.sourceType ?? "Source",
        coveredBytes: covered,
        totalBytes: resource.totalBytes,
        percent: percent(covered, resource.totalBytes),
      };
    })
    .sort((left, right) => left.kind.localeCompare(right.kind) || left.url.localeCompare(right.url));
  const summary = ["JavaScript", "CSS"].map((kind) => {
    const matching = rows.filter((row) => row.kind === kind);
    const covered = matching.reduce((total, row) => total + row.coveredBytes, 0);
    const total = matching.reduce((sum, row) => sum + row.totalBytes, 0);
    return { kind, coveredBytes: covered, totalBytes: total, percent: percent(covered, total) };
  });

  await writeFile(
    path.join(coverageRoot, "coverage-summary.json"),
    JSON.stringify({ generatedAt: new Date().toISOString(), summary, resources: rows }, null, 2),
  );
  const cards = summary
    .map((item) => `<article><h2>${item.kind}</h2><strong>${item.percent}%</strong><span>${item.coveredBytes.toLocaleString()} / ${item.totalBytes.toLocaleString()} bytes</span></article>`)
    .join("");
  const tableRows = rows
    .map((row) => `<tr><td>${row.kind}</td><td title="${escapeHtml(row.url)}"><a href="${escapeHtml(row.detailPath)}">${escapeHtml(row.displayName)}</a> <small>${escapeHtml(row.sourceType)} · ${row.sourceHash.slice(0, 8)}</small></td><td>${row.percent}%</td><td>${row.coveredBytes.toLocaleString()} / ${row.totalBytes.toLocaleString()}</td></tr>`)
    .join("");
  await writeFile(
    path.join(coverageRoot, "index.html"),
    `<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>NTOJ browser coverage</title><style>body{font:15px system-ui;margin:0;background:#f5f7fb;color:#18212f}main{max-width:1100px;margin:auto;padding:32px}h1{margin-bottom:4px}.note{color:#5d6878}.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:16px;margin:24px 0}.cards article{background:white;border-radius:12px;padding:20px;box-shadow:0 2px 12px #2233aa14}.cards strong{display:block;font-size:36px;color:#3157d5}.cards span{color:#687386}table{width:100%;border-collapse:collapse;background:white;border-radius:12px;overflow:hidden;box-shadow:0 2px 12px #2233aa14}th,td{text-align:left;padding:11px 14px;border-bottom:1px solid #e8ebf2}th{background:#eef2ff}td:nth-child(3){font-weight:700}td a{color:#3157d5;text-decoration:none;font-family:ui-monospace,SFMono-Regular,Consolas,monospace}td a:hover{text-decoration:underline}small{display:block;color:#8992a3;margin-top:3px}</style></head><body><main><h1>NTOJ browser coverage</h1><p class="note">Playwright Chromium runtime byte coverage. Same-origin application scripts and styles only; third-party assets are excluded. Select a resource to inspect line-numbered, highlighted source.</p><section class="cards">${cards}</section><table><thead><tr><th>Type</th><th>Resource</th><th>Used</th><th>Covered bytes</th></tr></thead><tbody>${tableRows}</tbody></table></main></body></html>`,
  );
}

function addResource(
  resources: Map<string, ResourceCoverage>,
  kind: "JavaScript" | "CSS",
  url: string,
  source: string,
  ranges: ByteRange[],
): void {
  const sourceHash = createHash("sha1").update(source).digest("hex");
  const key = `${kind}:${url}:${sourceHash}`;
  const existing = resources.get(key) ?? {
    kind,
    url,
    sourceHash,
    source,
    totalBytes: source.length,
    coveredRanges: [],
  };
  existing.coveredRanges = mergeRanges(
    [...existing.coveredRanges, ...ranges],
    existing.totalBytes,
  );
  resources.set(key, existing);
}
