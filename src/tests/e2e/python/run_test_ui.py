from __future__ import annotations

import argparse
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import subprocess
import sys
import webbrowser


E2E_DIR = Path(__file__).resolve().parent
RESULTS_DIR = E2E_DIR / "test-dashboard"
REPORT_PATH = RESULTS_DIR / "dashboard.html"


class QuietReportHandler(SimpleHTTPRequestHandler):
    def log_message(self, format: str, *args) -> None:
        return


def parse_args() -> tuple[argparse.Namespace, list[str]]:
    parser = argparse.ArgumentParser(
        description="Run NTOJ Playwright tests and open the Python HTML test dashboard.",
        epilog="Unknown arguments are forwarded to pytest, for example: -m contest -k scoreboard",
    )
    parser.add_argument("--host", default="127.0.0.1", help="Dashboard server host")
    parser.add_argument("--port", default=8765, type=int, help="Dashboard server port")
    parser.add_argument("--no-open", action="store_true", help="Do not open the system browser")
    parser.add_argument("--no-serve", action="store_true", help="Generate the report without starting a server")
    parser.add_argument(
        "--serve-existing",
        action="store_true",
        help="Open the existing dashboard without running pytest",
    )
    options, pytest_args = parser.parse_known_args()
    if pytest_args[:1] == ["--"]:
        pytest_args = pytest_args[1:]
    return options, pytest_args


def run_pytest(pytest_args: list[str]) -> int:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    command = [
        sys.executable,
        "-m",
        "pytest",
        "-c",
        str(E2E_DIR / "pytest.ini"),
        ".",
        f"--html={REPORT_PATH}",
        "--self-contained-html",
        f"--css={E2E_DIR / 'test-report.css'}",
        *pytest_args,
    ]
    print("Running:", " ".join(map(str, command)), flush=True)
    return subprocess.run(command, cwd=E2E_DIR, check=False).returncode


def serve_report(host: str, port: int, *, open_browser: bool) -> None:
    handler = partial(QuietReportHandler, directory=str(RESULTS_DIR))
    server = ThreadingHTTPServer((host, port), handler)
    url = f"http://{host}:{port}/{REPORT_PATH.name}"
    print(f"NTOJ E2E dashboard: {url}", flush=True)
    print("Press Ctrl+C to stop the dashboard server.", flush=True)
    if open_browser:
        webbrowser.open_new_tab(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nDashboard server stopped.", flush=True)
    finally:
        server.server_close()


def main() -> int:
    options, pytest_args = parse_args()
    exit_code = 0
    if not options.serve_existing:
        exit_code = run_pytest(pytest_args)
    elif not REPORT_PATH.exists():
        print(f"Dashboard does not exist yet: {REPORT_PATH}", file=sys.stderr)
        return 2

    if not REPORT_PATH.exists():
        print("pytest did not produce the HTML dashboard.", file=sys.stderr)
        return exit_code or 2

    print(f"Dashboard written to: {REPORT_PATH}", flush=True)
    if not options.no_serve:
        serve_report(options.host, options.port, open_browser=not options.no_open)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
