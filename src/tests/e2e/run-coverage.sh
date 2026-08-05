#!/bin/bash

set -uo pipefail

cd "$(dirname "$0")/../../.."
repo_root=$PWD

for required_command in docker flock; do
  if ! command -v "$required_command" >/dev/null 2>&1; then
    echo "Missing required command: $required_command" >&2
    exit 127
  fi
done
if ! docker compose version >/dev/null 2>&1; then
  echo "Docker Compose v2 is required." >&2
  exit 127
fi

# The workflow shares coverage files, screenshots, videos, and Playwright
# reports in the checkout. Serialize even when Compose projects are isolated.
exec 9>/tmp/ntoj-e2e-coverage.lock
if ! flock -n 9; then
  echo another-ntoj-coverage-workflow-is-already-running >&2
  exit 75
fi

project_name=${NTOJ_E2E_PROJECT_NAME:-ntoj-e2e}
integration_project_name=${NTOJ_INTEGRATION_PROJECT_NAME:-${project_name}-integration}
keep_environment=${NTOJ_E2E_KEEP_ENVIRONMENT:-1}
start_ui=${NTOJ_E2E_START_UI:-$keep_environment}
serve_coverage=${NTOJ_E2E_SERVE_COVERAGE:-$keep_environment}
log_dir=${NTOJ_E2E_LOG_DIR:-}

for toggle_name in keep_environment start_ui serve_coverage; do
  toggle_value=${!toggle_name}
  if [[ "$toggle_value" != 0 && "$toggle_value" != 1 ]]; then
    echo "$toggle_name must be 0 or 1 (received: $toggle_value)" >&2
    exit 2
  fi
done

compose=(
  docker compose
  -p "$project_name"
  -f src/tests/e2e/docker-compose.yml
  -f src/tests/e2e/docker-compose.node.yml
  -f src/tests/e2e/docker-compose.coverage.yml
)
base_compose=(
  docker compose
  -p "$project_name"
  -f src/tests/e2e/docker-compose.yml
  -f src/tests/e2e/docker-compose.node.yml
)
integration_compose=(
  docker compose
  -p "$integration_project_name"
  -f src/tests/e2e/docker-compose.yml
)

test_status=0
unit_status=0
integration_status=0
report_status=0
backend_touched=0
ui_paused=0
current_phase=initializing
active_marker=src/tests/e2e/node/.coverage-workflow-active

run_required() {
  local label=$1
  shift
  current_phase=$label
  echo "==> $label"
  "$@"
  local status=$?
  if (( status != 0 )); then
    echo "Required deployment-test step failed ($status): $label" >&2
    exit "$status"
  fi
}

wait_for_service_port() {
  local host=$1
  local port=$2
  local label=$3
  local attempt
  for ((attempt = 1; attempt <= 45; attempt++)); do
    if "${compose[@]}" exec -T backend python3 -c \
      "import socket; connection = socket.create_connection(('${host}', ${port}), 2); connection.close()" \
      >/dev/null 2>&1; then
      return 0
    fi
    sleep 2
  done
  echo "Timed out waiting for $label at ${host}:${port}" >&2
  return 1
}

capture_diagnostics() {
  if [[ -z "$log_dir" ]]; then
    return 0
  fi

  mkdir -p "$log_dir"
  {
    printf 'captured_at=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    printf 'project_name=%s\n' "$project_name"
    printf 'integration_project_name=%s\n' "$integration_project_name"
    docker version || true
    docker compose version || true
  } >"$log_dir/environment.txt" 2>&1
  "${compose[@]}" config >"$log_dir/compose-config.yml" 2>"$log_dir/compose-config.stderr" || true
  "${compose[@]}" --profile judge ps -a >"$log_dir/e2e-containers.txt" 2>&1 || true
  "${compose[@]}" --profile judge logs --no-color >"$log_dir/e2e-compose.log" 2>&1 || true
  "${integration_compose[@]}" --profile judge ps -a >"$log_dir/integration-containers.txt" 2>&1 || true
  "${integration_compose[@]}" --profile judge logs --no-color >"$log_dir/integration-compose.log" 2>&1 || true
}

cleanup() {
  local workflow_status=$?
  trap - EXIT

  rm -f "$active_marker"
  if [[ -n "$log_dir" ]]; then
    {
      printf 'workflow_exit_code=%s\n' "$workflow_status"
      printf 'last_phase=%s\n' "$current_phase"
      printf 'playwright_exit_code=%s\n' "$test_status"
      printf 'unit_exit_code=%s\n' "$unit_status"
      printf 'integration_exit_code=%s\n' "$integration_status"
      printf 'report_exit_code=%s\n' "$report_status"
    } >"$log_dir/coverage-status.txt"
  fi
  capture_diagnostics
  "${integration_compose[@]}" --profile judge down -v --remove-orphans >/dev/null 2>&1 || true

  if (( keep_environment == 0 )); then
    "${compose[@]}" --profile judge down -v --remove-orphans >/dev/null 2>&1 || true
  else
    if (( backend_touched != 0 )); then
      "${base_compose[@]}" up -d --force-recreate backend || true
    fi
    if (( start_ui != 0 && ui_paused != 0 )); then
      "${base_compose[@]}" up -d --force-recreate node-tests || true
    fi
  fi

  exit "$workflow_status"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

if (( start_ui != 0 )); then
  run_required "pause the interactive Playwright UI" "${base_compose[@]}" stop -t 10 node-tests
  ui_paused=1
fi
touch "$active_marker"

run_required "build the development backend" "${compose[@]}" build backend
backend_touched=1
run_required "clear per-suite Python coverage data" \
  "${compose[@]}" run --rm --no-deps --entrypoint bash backend -lc \
  'mkdir -p /coverage/python/suites/e2e /coverage/python/suites/unit /coverage/python/suites/integration && rm -f /coverage/python/suites/e2e/.coverage* /coverage/python/suites/unit/.coverage* /coverage/python/suites/integration/.coverage* && /root/.local/bin/poetry run coverage erase --rcfile=/ntoj/tests/e2e/python-coveragerc'
run_required "start the privileged Judge" "${compose[@]}" --profile judge up -d judge-server
run_required "start the instrumented backend" "${compose[@]}" up -d backend
run_required "wait for the Judge socket" wait_for_service_port judge 2502 Judge
run_required "restart the backend after Judge discovery" "${compose[@]}" restart backend
run_required "wait for the NTOJ HTTP socket" wait_for_service_port 127.0.0.1 5500 NTOJ

current_phase=playwright
"${compose[@]}" run --rm --no-deps \
  -e NTOJ_E2E_COVERAGE_OWNER=run-coverage node-headless \
  bash -lc "npm ci --no-audit --no-fund && npm run typecheck && npm test" || test_status=$?

# coverage.py writes in-process data when the server receives SIGTERM.
current_phase=e2e-python-coverage
"${compose[@]}" stop -t 20 backend || report_status=$?
"${compose[@]}" run --rm --no-deps --entrypoint bash backend -lc \
  'COVERAGE_FILE=/coverage/python/suites/e2e/.coverage /root/.local/bin/poetry run coverage combine --keep --rcfile=/ntoj/tests/e2e/python-coveragerc /coverage/python/suites/e2e' \
  || report_status=$?

# Unit coverage uses a separate suite file so it unions cleanly with execution
# observed through the browser-driven backend.
current_phase=unit
"${compose[@]}" run --rm --no-deps --entrypoint bash backend -lc \
  'cp config-tmp.py config.py && PATH=/root/.local/bin:/usr/local/bin:/usr/bin COVERAGE_FILE=/coverage/python/suites/unit/.coverage poetry run coverage run --rcfile=tests/e2e/python-coveragerc rununittest.py; status=$?; PATH=/root/.local/bin:/usr/local/bin:/usr/bin COVERAGE_FILE=/coverage/python/suites/unit/.coverage poetry run coverage combine --keep --rcfile=tests/e2e/python-coveragerc /coverage/python/suites/unit || true; exit $status' \
  || unit_status=$?

# Run the real Judge integration in a separate Compose project so its database
# and Redis state cannot interfere with Playwright's disposable site.
current_phase=integration
"${integration_compose[@]}" build backend || integration_status=$?
if (( integration_status == 0 )); then
  "${integration_compose[@]}" up -d --wait db cache || integration_status=$?
fi
if (( integration_status == 0 )); then
  "${integration_compose[@]}" --profile judge up -d judge-server || integration_status=$?
fi
if (( integration_status == 0 )); then
  "${integration_compose[@]}" run --rm --no-deps \
    -v "$repo_root/src/tests/e2e/coverage/python:/coverage/python" \
    --entrypoint bash backend -lc \
    'cp config-tmp.py config.py && env PATH=/root/.local/bin:/usr/local/bin:/usr/bin bash ./runintegratedtest.sh; status=$?; if [[ -f .coverage ]]; then cp .coverage /coverage/python/suites/integration/.coverage; fi; exit $status' \
    || integration_status=$?
fi

# Publish one Python source report that unions all three suite data files. The
# publisher optionally starts the local dashboard; deployment mode only keeps
# the static artifact.
current_phase=coverage-report
NTOJ_E2E_SERVE_COVERAGE="$serve_coverage" \
  bash src/tests/e2e/publish-total-coverage.sh || report_status=$?

printf 'Coverage workflow statuses: '
declare -p test_status unit_status integration_status report_status

final_status=$report_status
if (( integration_status != 0 )); then
  final_status=$integration_status
fi
if (( unit_status != 0 )); then
  final_status=$unit_status
fi
if (( test_status != 0 )); then
  final_status=$test_status
fi
current_phase=completed
exit "$final_status"
