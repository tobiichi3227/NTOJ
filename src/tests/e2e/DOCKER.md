# Disposable Docker environment

The E2E Compose project uses named volumes, host port `5502` for NTOJ, and
loopback-only host port `9323` for Playwright UI. It does not reuse the fixed
`/srv/ntoj-dev` data directories from `docker-compose.dev.yml`.

The Node runner uses the version-matched official image
`mcr.microsoft.com/playwright:v1.61.1-noble`. Dependencies are installed from
`node/package-lock.json` into a Docker volume, so no host `node_modules`
directory is needed.

## Start Playwright UI

```bash
docker compose \
  -f src/tests/e2e/docker-compose.yml \
  -f src/tests/e2e/docker-compose.node.yml \
  up -d --build node-tests
```

- Playwright UI: <http://127.0.0.1:9323>
- disposable NTOJ: <http://127.0.0.1:5502>

Follow the UI logs:

```bash
docker compose \
  -f src/tests/e2e/docker-compose.yml \
  -f src/tests/e2e/docker-compose.node.yml \
  logs -f node-tests
```

## Run headlessly

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

To run only Contest coverage, append `--grep @contest` to the Playwright
command.

## Judge profile

The normal suite intentionally omits the Judge. Its image is built from the
remote `NTOJ-Judge-Rewrite` repository, and the service is privileged, mounts
the host cgroup filesystem read-write, and receives `SYS_ADMIN`. Review and
explicitly approve that trust boundary before starting it.

Start the Judge, then restart the backend after the Judge is listening so the
backend establishes its WebSocket connection:

```bash
docker compose \
  -f src/tests/e2e/docker-compose.yml \
  -f src/tests/e2e/docker-compose.node.yml \
  --profile judge up -d --build backend judge-server

docker compose \
  -f src/tests/e2e/docker-compose.yml \
  -f src/tests/e2e/docker-compose.node.yml \
  restart backend

docker compose \
  -f src/tests/e2e/docker-compose.yml \
  -f src/tests/e2e/docker-compose.node.yml \
  run --rm --no-deps \
  node-headless \
  bash -lc "npm ci --no-audit --no-fund && npx playwright test --grep @judge"
```

The suite defaults to seeded problem `1`, promotes it to Online with submission
enabled, and uses its bundled `HelloTOJ` G++ testdata. Override the ID with
`NTOJ_E2E_PROBLEM_ID` only when the replacement problem accepts the same
fixture.

The thirteen Judge tests cover the seeded problem and compiler UI, C++ and
Python AC, WA, RE, RESIG, TLE, CE diagnostics, submission validation, source
privacy, administrator rejudge, IOI Contest score propagation, and ACM
WA-before-AC penalty. RESIG is currently an expected failure documented in
[`JUDGE_SPEC_DIFFERENCES.md`](JUDGE_SPEC_DIFFERENCES.md). Traces, PNG
screenshots, and WebM videos are recorded for every test.

## Coverage environment

`docker-compose.coverage.yml` instruments the development backend with
coverage.py, enables Playwright Chromium JS/CSS coverage, persists both reports
under `coverage/`, and exposes the combined report server on loopback port
`9325`.

Use the lifecycle runner rather than starting the override manually; it flushes
Python coverage with SIGTERM and restores the ordinary backend afterward:

```bash
bash src/tests/e2e/run-coverage.sh
```

Open <http://127.0.0.1:9325>. See [`COVERAGE.md`](COVERAGE.md) for report paths,
measurement semantics, and current percentages.

## Cleanup

```bash
docker compose \
  -f src/tests/e2e/docker-compose.yml \
  -f src/tests/e2e/docker-compose.node.yml \
  down -v
```

This removes only the disposable E2E containers, networks, and named volumes.