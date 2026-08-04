import { createHash } from "node:crypto";
import { mkdir, writeFile } from "node:fs/promises";
import * as path from "node:path";

export type SourceCoverageRange = {
  start: number;
  end: number;
};

export type SourceCoverageResource = {
  kind: "JavaScript" | "CSS";
  url: string;
  sourceHash: string;
  source: string;
  totalBytes: number;
  coveredRanges: SourceCoverageRange[];
};

export type SourceCoverageDetail = {
  detailPath: string;
  displayName: string;
  sourceType: string;
};

export function sourceCoverageKey(resource: {
  kind: "JavaScript" | "CSS";
  url: string;
  sourceHash: string;
}): string {
  return `${resource.kind}:${resource.url}:${resource.sourceHash}`;
}

export async function writeSourceCoverageReports(
  coverageRoot: string,
  resources: SourceCoverageResource[],
): Promise<Map<string, SourceCoverageDetail>> {
  const detailDirectory = path.join(coverageRoot, "files");
  await mkdir(detailDirectory, { recursive: true });
  const details = new Map<string, SourceCoverageDetail>();

  await Promise.all(
    resources.map(async (resource) => {
      const identity = sourceCoverageKey(resource);
      const reportId = createHash("sha1").update(identity).digest("hex").slice(0, 20);
      const detailPath = `files/${reportId}.html`;
      const descriptor = describeResource(resource);
      details.set(identity, { detailPath, ...descriptor });
      await writeFile(
        path.join(coverageRoot, detailPath),
        renderSourcePage(resource, descriptor),
      );
    }),
  );

  return details;
}

function describeResource(resource: SourceCoverageResource): {
  displayName: string;
  sourceType: string;
} {
  const url = new URL(resource.url);
  const isSourceFile = resource.kind === "JavaScript"
    ? url.pathname.endsWith(".js")
    : url.pathname.endsWith(".css");
  return {
    displayName: isSourceFile
      ? url.pathname
      : `inline @ ${url.pathname} #${resource.sourceHash.slice(0, 8)}`,
    sourceType: isSourceFile ? "Source file" : `Inline ${resource.kind}`,
  };
}

function renderSourcePage(
  resource: SourceCoverageResource,
  descriptor: { displayName: string; sourceType: string },
): string {
  const covered = resource.coveredRanges.reduce(
    (total, range) => total + range.end - range.start,
    0,
  );
  const percentage = resource.totalBytes === 0
    ? 100
    : Number(((covered / resource.totalBytes) * 100).toFixed(2));
  const sourceLines = renderSourceLines(resource.source, resource.coveredRanges);

  return `<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width">
  <title>${escapeHtml(descriptor.displayName)} · NTOJ browser coverage</title>
  <style>
    :root{color-scheme:light dark}*{box-sizing:border-box}body{font:14px system-ui;margin:0;background:#f5f7fb;color:#18212f}header{position:sticky;top:0;z-index:2;background:#fff;border-bottom:1px solid #dfe4ee;padding:18px 24px;box-shadow:0 2px 10px #2233aa12}header a{color:#3157d5;text-decoration:none}h1{font:600 20px ui-monospace,SFMono-Regular,Consolas,monospace;margin:8px 0;overflow-wrap:anywhere}.meta{display:flex;flex-wrap:wrap;gap:18px;color:#5d6878}.meta strong{color:#3157d5}.legend{display:flex;gap:14px;margin-top:10px}.legend span::before{content:"";display:inline-block;width:12px;height:12px;margin-right:5px;border-radius:2px;vertical-align:-1px}.legend .covered::before{background:#c9f2d3}.legend .partial::before{background:#fff0ad}.legend .missed::before{background:#ffd4d4}main{min-width:max-content;padding:18px 0 40px}.line{display:grid;grid-template-columns:72px minmax(600px,1fr);min-height:20px}.line:hover{background:#eaf0ff}.line-number{position:sticky;left:0;padding:0 14px 0 8px;text-align:right;color:#8892a3;text-decoration:none;user-select:none;background:#edf0f6;border-right:1px solid #d7dce6}.line.hit .line-number{background:#d9f5df;color:#28723a}.line.partial .line-number{background:#fff0ad;color:#825f00}.line.miss .line-number{background:#ffdede;color:#9b2727}.line code{white-space:pre;padding:0 12px;font:13px/20px ui-monospace,SFMono-Regular,Consolas,"Liberation Mono",monospace}.segment-covered{background:#c9f2d3;color:#16371e}.segment-missed{background:#ffd4d4;color:#541b1b}@media(prefers-color-scheme:dark){body{background:#10141d;color:#dce3ef}header{background:#171d28;border-color:#313a49}.line:hover{background:#1a2539}.line-number{background:#1a202b;border-color:#343d4c}.segment-covered{background:#214d2c;color:#e1f7e6}.segment-missed{background:#572929;color:#ffe5e5}}
  </style>
</head>
<body>
  <header>
    <a href="../index.html">← Browser coverage summary</a>
    <h1>${escapeHtml(descriptor.displayName)}</h1>
    <div class="meta"><span>${escapeHtml(descriptor.sourceType)}</span><span title="${escapeHtml(resource.url)}">${escapeHtml(resource.url)}</span><span><strong>${percentage}%</strong> · ${covered.toLocaleString()} / ${resource.totalBytes.toLocaleString()} covered bytes</span></div>
    <div class="legend"><span class="covered">covered</span><span class="partial">partially covered</span><span class="missed">not covered</span></div>
  </header>
  <main>${sourceLines}</main>
</body>
</html>`;
}

function renderSourceLines(source: string, ranges: SourceCoverageRange[]): string {
  const lines = source.split("\n");
  let offset = 0;
  return lines
    .map((line, index) => {
      const start = offset;
      const end = start + line.length;
      offset = end + 1;
      const segments = renderLineSegments(source, start, end, ranges);
      const covered = intersectionLength(start, end, ranges);
      const status = line.trim().length === 0
        ? "neutral"
        : covered === 0
          ? "miss"
          : covered >= line.length
            ? "hit"
            : "partial";
      const lineNumber = index + 1;
      return `<div class="line ${status}" id="L${lineNumber}"><a class="line-number" href="#L${lineNumber}">${lineNumber}</a><code>${segments || "&nbsp;"}</code></div>`;
    })
    .join("");
}

function renderLineSegments(
  source: string,
  start: number,
  end: number,
  ranges: SourceCoverageRange[],
): string {
  if (end <= start) return "";
  const pieces: string[] = [];
  let cursor = start;
  for (const range of ranges) {
    if (range.end <= start) continue;
    if (range.start >= end) break;
    const coveredStart = Math.max(cursor, start, range.start);
    const coveredEnd = Math.min(end, range.end);
    if (coveredStart > cursor) {
      pieces.push(`<span class="segment-missed">${escapeHtml(source.slice(cursor, coveredStart))}</span>`);
    }
    if (coveredEnd > coveredStart) {
      pieces.push(`<span class="segment-covered">${escapeHtml(source.slice(coveredStart, coveredEnd))}</span>`);
      cursor = coveredEnd;
    }
  }
  if (cursor < end) {
    pieces.push(`<span class="segment-missed">${escapeHtml(source.slice(cursor, end))}</span>`);
  }
  return pieces.join("");
}

function intersectionLength(
  start: number,
  end: number,
  ranges: SourceCoverageRange[],
): number {
  return ranges.reduce((total, range) => {
    const intersection = Math.min(end, range.end) - Math.max(start, range.start);
    return total + Math.max(0, intersection);
  }, 0);
}

function escapeHtml(value: string): string {
  return value
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}
