from __future__ import annotations

import argparse
import os
from pathlib import Path
import subprocess
import sys
import webbrowser


E2E_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = E2E_DIR.parents[3]
RESULTS_DIR = E2E_DIR / "test-results" / "e2e-ui"


def parse_args() -> tuple[argparse.Namespace, list[str]]:
    parser = argparse.ArgumentParser(
        description="Launch the Python Playwright E2E suite with an Inspector UI or HTML dashboard.",
    )
    parser.add_argument(
        "--report",
        action="store_true",
        help="Generate and open an HTML dashboard instead of launching Playwright Inspector.",
    )
    parser.add_argument(
        "--no-open",
        action="store_true",
        help="Do not open the generated HTML report automatically.",
    )
    parser.add_argument(
        "--slowmo",
        type=int,
        default=150,
        help="Inspector browser action delay in milliseconds (default: 150).",
    )
    return parser.parse_known_args()


def main() -> int:
    args, pytest_args = parse_args()
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    artifacts_dir = RESULTS_DIR / "artifacts"
    command = [
        sys.executable,
        "-m",
        "pytest",
        "-c",
        str(E2E_DIR / "pytest.ini"),
        str(E2E_DIR),
        "--tracing=retain-on-failure",
        "--screenshot=only-on-failure",
        "--video=retain-on-failure",
        f"--output={artifacts_dir}",
    ]
    env = os.environ.copy()

    if args.report:
        report_path = RESULTS_DIR / "report.html"
        command.extend([f"--html={report_path}", "--self-contained-html"])
    else:
        env["PWDEBUG"] = "1"
        command.extend(["-s", "--headed", f"--slowmo={args.slowmo}"])

    command.extend(pytest_args)
    result = subprocess.run(command, cwd=PROJECT_ROOT, env=env, check=False)

    if args.report and not args.no_open:
        webbrowser.open(report_path.resolve().as_uri())
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
