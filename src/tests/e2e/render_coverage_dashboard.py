#!/usr/bin/env python3
"""Render the self-contained coverage landing page served on port 9325."""

from __future__ import annotations

import argparse
import html
import json
from datetime import datetime
from pathlib import Path


SUITE_LABELS = {
    "e2e": "Browser E2E",
    "integration": "Integrated",
    "unit": "Unit",
}


def load_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise SystemExit(f"Missing coverage input: {path}") from exc


def metric_card(label: str, value: str, detail: str, css_class: str = "") -> str:
    return f"""
      <article class="metric {css_class}">
        <span>{html.escape(label)}</span>
        <strong>{html.escape(value)}</strong>
        <small>{html.escape(detail)}</small>
      </article>"""


def render(coverage_root: Path) -> Path:
    python_report = load_json(coverage_root / "python" / "coverage.json")
    browser_report = load_json(coverage_root / "web" / "coverage-summary.json")
    totals = python_report["totals"]
    browser = {item["kind"]: item for item in browser_report["summary"]}

    suite_root = coverage_root / "python" / "suites"
    suite_dirs = {
        path.parent.name for path in suite_root.glob("*/.coverage*") if path.is_file()
    }
    suite_names = [
        SUITE_LABELS.get(name, name.replace("-", " ").title())
        for name in sorted(suite_dirs)
    ]
    suite_text = " + ".join(suite_names) if suite_names else "Combined Python suites"

    combined = totals["percent_covered_display"] + "%"
    statements = totals["percent_statements_covered_display"] + "%"
    branches = totals["percent_branches_covered_display"] + "%"
    javascript = browser["JavaScript"]
    css = browser["CSS"]
    generated_at = python_report.get("meta", {}).get("timestamp", "unknown")
    try:
        generated_at = datetime.fromisoformat(generated_at).astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")
    except ValueError:
        pass

    page = f"""<!doctype html>
<html lang="zh-Hant">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width">
    <title>NTOJ Total Coverage</title>
    <style>
      :root {{ color-scheme: dark; --bg:#08111f; --panel:#101d31; --line:#223653;
        --text:#edf5ff; --muted:#91a5c3; --accent:#67e8f9; --good:#5ee6a8; }}
      * {{ box-sizing:border-box; }}
      body {{ margin:0; min-height:100vh; font:15px/1.55 Inter,ui-sans-serif,system-ui,sans-serif;
        color:var(--text); background:radial-gradient(circle at 10% 0,#173153 0,transparent 38%),var(--bg); }}
      main {{ width:min(1080px,calc(100% - 32px)); margin:auto; padding:56px 0 72px; }}
      .eyebrow {{ color:var(--accent); font-weight:800; letter-spacing:.14em; text-transform:uppercase; }}
      h1 {{ margin:6px 0 8px; font-size:clamp(34px,7vw,66px); line-height:1; }}
      .lead,.note {{ color:var(--muted); max-width:780px; }}
      .hero {{ display:grid; grid-template-columns:minmax(260px,1.2fr) minmax(280px,2fr); gap:20px;
        margin:34px 0 20px; }}
      .total,.metric,.report {{ border:1px solid var(--line); border-radius:18px;
        background:linear-gradient(145deg,#142642e8,#0d192be8); box-shadow:0 18px 55px #0005; }}
      .total {{ padding:30px; display:flex; flex-direction:column; justify-content:center; }}
      .total strong {{ color:var(--good); font-size:clamp(62px,10vw,104px); line-height:1; letter-spacing:-.06em; }}
      .total span {{ color:var(--muted); margin-top:12px; }}
      .metrics {{ display:grid; grid-template-columns:repeat(2,1fr); gap:14px; }}
      .metric {{ padding:21px; }}
      .metric span,.metric small {{ display:block; color:var(--muted); }}
      .metric strong {{ display:block; margin:5px 0; font-size:34px; color:var(--accent); }}
      .metric.backend strong {{ color:var(--good); }}
      .reports {{ display:grid; grid-template-columns:repeat(2,1fr); gap:16px; margin-top:20px; }}
      .report {{ display:block; padding:24px; color:inherit; text-decoration:none; transition:.18s ease; }}
      .report:hover {{ transform:translateY(-3px); border-color:var(--accent); }}
      .report strong {{ display:block; font-size:21px; }}
      .report span {{ color:var(--muted); }}
      .note {{ margin-top:22px; padding:14px 16px; border-left:3px solid var(--accent); background:#0c192a; }}
      footer {{ margin-top:22px; color:#6f86a8; font-size:13px; }}
      @media (max-width:760px) {{ .hero,.reports {{ grid-template-columns:1fr; }} }}
    </style>
  </head>
  <body>
    <main>
      <div class="eyebrow">NTOJ quality cockpit</div>
      <h1>Total coverage</h1>
      <p class="lead">同一份 coverage.py data 內 union 所有測試執行路徑，不是把百分比相加或取平均。</p>
      <section class="hero">
        <article class="total">
          <strong data-testid="python-total">{combined}</strong>
          <span>Python line + branch · {html.escape(suite_text)}</span>
        </article>
        <div class="metrics">
          {metric_card("Python statements", statements, f"{totals['covered_lines']:,} / {totals['num_statements']:,} lines", "backend")}
          {metric_card("Python branches", branches, f"{totals['covered_branches']:,} / {totals['num_branches']:,} branches", "backend")}
          {metric_card("JavaScript bytes", f"{javascript['percent']:.2f}%", f"{javascript['coveredBytes']:,} / {javascript['totalBytes']:,} bytes")}
          {metric_card("CSS bytes", f"{css['percent']:.2f}%", f"{css['coveredBytes']:,} / {css['totalBytes']:,} bytes")}
        </div>
      </section>
      <section class="reports">
        <a class="report" href="/python/html/"><strong>Python source report →</strong><span>逐檔 line、branch 與 missing lines</span></a>
        <a class="report" href="/web/"><strong>Browser source report →</strong><span>Playwright Chromium JS/CSS runtime bytes</span></a>
      </section>
      <p class="note">Python 與瀏覽器 coverage 使用不同分母，因此刻意分開顯示，不製造沒有統計意義的跨語言平均數。</p>
      <footer>Generated {html.escape(str(generated_at))}</footer>
    </main>
  </body>
</html>
"""
    output = coverage_root / "index.html"
    temporary = output.with_suffix(".html.tmp")
    temporary.write_text(page, encoding="utf-8")
    temporary.replace(output)
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description="Render the NTOJ total coverage landing page")
    parser.add_argument(
        "coverage_root",
        nargs="?",
        type=Path,
        default=Path(__file__).resolve().parent / "coverage",
    )
    args = parser.parse_args()
    print(render(args.coverage_root.resolve()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
