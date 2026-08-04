# Deployment test gate

The deployment entrypoint runs the complete test system: Node.js Playwright,
Python unit coverage, the real integration suite, the privileged Judge, browser
coverage, and the aggregate Python coverage gate.

## Host prerequisites

The runner must provide:

- a Linux Docker Engine accessible by the current user
- Docker Compose v2 and `flock`
- the host `/sys/fs/cgroup` filesystem
- permission to launch the Judge with `privileged`, `SYS_ADMIN`, and a read-write
  cgroup bind mount
- outbound access for the project images and the Judge build context

The Judge is the same trusted privileged component used by the development and
release Compose files. Do not run this workflow on an untrusted shared Docker
host.

## Canonical command

From the repository root:

```bash
src/tests/e2e/run-deployment-tests.sh
```

The deployment wrapper performs a preflight check, allocates a unique Compose
project, assigns ephemeral host ports, runs `run-coverage.sh`, enforces 100%
Python statement coverage and 100% Python branch coverage independently,
records diagnostics, and removes all containers, networks, and test-only
volumes before returning. Any setup, test, coverage, or cleanup-visible test
failure produces a non-zero exit code.

Set the threshold explicitly when wrapping the gate in another pipeline:

```bash
NTOJ_PYTHON_COVERAGE_MIN=100 src/tests/e2e/run-deployment-tests.sh
```

The Judge build defaults to the verified
`333334293b97aa65f506ec1bab8bab320570228b` commit. Test a deliberate Judge
upgrade by setting `NTOJ_JUDGE_BUILD_CONTEXT` to another Git URL and commit;
do not use a moving branch in a deployment gate.

Do not point this command at production data. It always creates its own
disposable database and storage volumes.

## GitHub Actions

The additive workflow `.github/workflows/deployment-tests.yml` can be started
manually from the Actions page. It is also a reusable workflow that an existing
deployment pipeline can place immediately before its deploy job. Both entry
points default to the 100% statement and branch gate:

```yaml
jobs:
  full-tests:
    uses: ./.github/workflows/deployment-tests.yml
    with:
      python_coverage_min: "100"

  deploy:
    needs: full-tests
    # deployment steps
```

The repository does not currently contain an actual deploy job, so the reusable
workflow does not silently alter release behavior. The deploy job must declare
`needs: full-tests`; GitHub will then skip deployment unless the complete test
gate passes.

## Artifacts and diagnostics

The workflow uploads one artifact bundle even when tests fail. It contains:

- `node/playwright-report/`: completed interactive HTML report
- `node/test-results/`: trace ZIPs, end-of-test PNG screenshots, WebM videos,
  and failure context
- `coverage/`: aggregate dashboard, Python per-file HTML, browser per-resource
  HTML, JSON summaries, and raw browser coverage
- `deployment-artifacts/<project-name>/`: preflight facts, overall exit status,
  Playwright/unit/integration/report exit codes, resolved Compose configuration,
  container state, cleanup verification, and logs for both Compose projects

Concurrent deployment wrappers use separate diagnostics subdirectories. The
shared Playwright and coverage outputs are protected by `flock`; a competing
run exits with code 75 instead of corrupting an active report.

For a local deployment-gate run, the same paths remain in the checkout after
Docker resources are removed. Open `coverage/index.html` and
`node/playwright-report/index.html` as static artifacts, or serve their parent
directories with a loopback-only HTTP server.

## Last verified run

On 2026-08-04 the deployment entrypoint completed in 8 minutes 30 seconds with
exit code 0. It reported 64 passed Playwright tests, 485 passed unit tests, a
successful privileged Judge integration run, and 100.00% statement and branch
coverage with zero missing items. All four recorded sub-stage exit codes were
zero. Cleanup verification found no remaining containers, volumes, or networks
for either isolated Compose project. The artifact contained 64 traces, 65
videos, and 76 PNG screenshots.

## Local interactive mode

`run-coverage.sh` remains the developer entrypoint. Its defaults preserve the
local backend, Playwright UI, and coverage server on ports 5502, 9323, and 9325.
The deployment wrapper explicitly disables those persistent services; the two
modes therefore share test logic without sharing lifecycle behavior.
