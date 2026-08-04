# E2E coverage

The coverage run measures both the Python backend exercised through HTTP,
WebSocket, and Judge callbacks, and the JavaScript/CSS executed by Chromium.

## Run

From the repository root, with the privileged Judge already approved and
available:

```bash
bash src/tests/e2e/run-coverage.sh
```

The runner performs the following lifecycle:

1. Builds the development backend, starts the approved privileged Judge, and
   starts the backend under `coverage.py` after Judge discovery.
2. Runs all Playwright tests with Chromium JS/CSS coverage enabled.
3. Stops the instrumented backend with SIGTERM so coverage data is saved.
4. Runs the unit suite into its own coverage data file.
5. Runs the Judge integration suite in an isolated Compose project and saves a
   third coverage data file.
6. Unions all three Python suites, generates the reports, and independently
   enforces the configured statement and branch thresholds (100% by default).
7. Refreshes the dashboard on <http://127.0.0.1:9325>.
8. Restores the ordinary non-instrumented backend.

Generated files live under `coverage/` and are ignored by Git, except for the
landing page and ignore rules. The Python suite inputs are kept separately at
`coverage/python/suites/{unit,integration,e2e}/.coverage*`; the canonical total
is written to `coverage/python/.coverage`.

To republish the total from the available suite data without rerunning
Playwright:

```bash
bash src/tests/e2e/publish-total-coverage.sh
```

## Reports

- Total coverage dashboard: <http://127.0.0.1:9325>
- Python line and branch report: <http://127.0.0.1:9325/python/html/>
- Browser JavaScript/CSS report: <http://127.0.0.1:9325/web/>
- Browser per-resource highlighted source: select any resource in the browser
  report; generated pages are stored under `coverage/web/files/`
- Python machine-readable data: `coverage/python/coverage.json`
- Browser machine-readable data: `coverage/web/coverage-summary.json`
- Per-test browser data: `coverage/web/raw/`

The current aggregate of the 485-test unit suite, privileged Judge integration,
and 64-test browser E2E run produced:

| Target | Coverage |
| --- | ---: |
| Python combined line/branch | 100.00% |
| Python statements | 100.00% |
| Python branches | 100.00% |
| Browser JavaScript bytes | 61.24% |
| Browser CSS bytes | 28.24% |

## How measurement works

Python uses coverage.py branch coverage and the same exclusion principles as
`src/runintegratedtest.sh`: tests, generated files, configuration, launchers,
migrations, and third-party packages are excluded. `scripts/runserver.sh`
activates instrumentation only when `NTOJ_COVERAGE_FILE` is set, so normal
development and release startup are unchanged.

`verify_python_coverage.py` reads coverage.py's JSON totals and checks statement
and branch percentages separately. At a 100% gate it additionally requires
both missing counters to be zero, preventing rounding from hiding an uncovered
line or branch.

The Python headline is coverage.py's union of the executable lines and branch
arcs reached by every available suite. It is not an average of suite
percentages. Browser coverage has a different byte-based denominator, so the
dashboard reports JavaScript and CSS separately instead of inventing a
cross-language percentage.

Browser coverage uses Playwright's built-in Chromium-only
`page.coverage.startJSCoverage()` and `startCSSCoverage()` APIs. The custom
reporter merges executed byte ranges across every test and BrowserContext.
Only same-origin NTOJ resources are counted; CDN and `/src/third/` assets are
excluded. These percentages are runtime byte coverage, not Istanbul statement
or branch coverage, and CSS injected without a source URL cannot be measured by
the Playwright API. The summary links each external source file and inline
page resource to a line-numbered detail page with covered, missed, and partial
byte-range highlighting.
