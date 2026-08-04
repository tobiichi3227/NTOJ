# NTOJ Playwright E2E

This is the Node.js Playwright Test suite for NTOJ. It exercises the rendered
application, SPA fragment loading, JavaScript handlers, browser sessions, and
WebSocket behavior.

The suite currently contains 64 Chromium tests across:

- authentication and account sessions
- public pages and standard user workflows
- administrator bulletins, boards, question replies, accounts, audit logs,
  system information, and official problem classes
- public problem and user rankings backed by real non-Contest Judge results
- Contest creation, registration, visibility, roles, problems, Q&A, and announcements
- Judge availability, C++/Python submission, AC, WA, RE, RESIG, TLE, CE,
  validation, source privacy, rejudge, and IOI/ACM Contest scoring
- Batch Judge configuration, compiler limits, testdata, subtasks, general
  settings, and safe file management

## Quick start: official Playwright UI

From the repository root:

```bash
docker compose \
  -f src/tests/e2e/docker-compose.yml \
  -f src/tests/e2e/docker-compose.node.yml \
  up -d --build node-tests
```

Open <http://127.0.0.1:9323>. The UI can run the whole suite, one file, or one
test; it also shows each action, DOM snapshots, source, network requests,
console output, complete traces, screenshots, and videos.

The disposable NTOJ site used by the tests is available at
<http://127.0.0.1:5502>.

## Headless run

Start the disposable backend, then run every test that does not require the
external Judge service:

```bash
docker compose \
  -f src/tests/e2e/docker-compose.yml \
  -f src/tests/e2e/docker-compose.node.yml \
  up -d --build backend

docker compose \
  -f src/tests/e2e/docker-compose.yml \
  -f src/tests/e2e/docker-compose.node.yml \
  run --rm --no-deps node-headless \
  bash -lc "npm ci --no-audit --no-fund && npx playwright test --grep-invert @judge"
```

Useful filters:

```bash
npx playwright test --grep @contest
npx playwright test --grep @judge
npx playwright test --grep @realtime
npx playwright test --grep @admin
npx playwright test tests/contest-lifecycle.spec.ts
```

The latest full run has 64 selected tests: 63 ordinary passes and one expected
failure documenting the external Judge's RESIG classification defect.
Playwright reports all 64 as passed. It records 64 traces, 65 videos, and 76
PNG screenshots.

Every selected test records a trace, an end-of-test PNG screenshot, and a WebM
video. The completed-run HTML report is written to `node/playwright-report/`; raw
artifacts are written to `node/test-results/`.

## Python and browser coverage

Run the combined coverage workflow from the repository root:

```bash
bash src/tests/e2e/run-coverage.sh
```

It measures Python line/branch coverage with coverage.py and Chromium
JavaScript/CSS runtime byte coverage with Playwright's built-in coverage API.
Open <http://127.0.0.1:9325> for the aggregate dashboard and both detailed
reports. The Python headline unions available unit, integrated, and E2E suite
data; JavaScript and CSS stay separate because they use byte coverage. See
[`COVERAGE.md`](COVERAGE.md) for details and current results.

## Deployment test gate

Run the complete deployment-safe test system with an isolated Compose project,
ephemeral host ports, automatic teardown, diagnostics, and independent 100%
Python statement and branch coverage thresholds:

```bash
src/tests/e2e/run-deployment-tests.sh
```

The manual/reusable GitHub Actions workflow is
[`.github/workflows/deployment-tests.yml`](../../../.github/workflows/deployment-tests.yml).
See [`DEPLOYMENT.md`](DEPLOYMENT.md) for host requirements, deployment-pipeline
wiring, failure behavior, and the uploaded Playwright/coverage artifacts.
## Local Node.js run

Docker is the reproducible default. To run with a local Node.js installation:

```bash
cd src/tests/e2e/node
npm ci
npx playwright install chromium
NTOJ_E2E_BASE_URL=http://127.0.0.1:5502 npm test
```

Use `npm run test:ui` for the local Playwright UI or `npm run test:contest` for
Contest tests.

Optional environment variables:

- `NTOJ_E2E_BASE_URL` defaults to `http://127.0.0.1:5502`.
- `NTOJ_E2E_ADMIN_EMAIL` defaults to `admin@admin` in Docker.
- `NTOJ_E2E_ADMIN_PASSWORD` defaults to `admin1234` in Docker.
- `NTOJ_E2E_PROBLEM_ID` selects the seeded Judge problem and defaults to `1`.

## Safety and cleanup

Only run the suite against disposable data. Tests create uniquely named users
and Contests, and the application does not provide deletion workflows for all
of them.

Stop the environment and delete its test-only volumes:

```bash
docker compose \
  -f src/tests/e2e/docker-compose.yml \
  -f src/tests/e2e/docker-compose.node.yml \
  down -v
```

See [`UI.md`](UI.md) for UI controls, [`DOCKER.md`](DOCKER.md) for environment
details, [`COVERAGE.md`](COVERAGE.md),
[`CONTEST_SPEC_DIFFERENCES.md`](CONTEST_SPEC_DIFFERENCES.md), and
[`JUDGE_SPEC_DIFFERENCES.md`](JUDGE_SPEC_DIFFERENCES.md) for confirmed
differences between `docs/` and the current implementation.

## Archived Python runner

The previous pytest-playwright implementation is preserved as a self-contained
suite under [`python/`](python/). Its tests, fixtures, requirements, Inspector
launcher, dashboard launcher, generated report, and ignore rules no longer
share paths with the primary Node.js runner.
