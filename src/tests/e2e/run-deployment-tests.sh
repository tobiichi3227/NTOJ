#!/bin/bash

set -Eeuo pipefail

cd "$(dirname "$0")/../../.."
repo_root=$PWD

artifact_root=${NTOJ_TEST_ARTIFACT_DIR:-src/tests/e2e/deployment-artifacts}
if [[ "$artifact_root" != /* ]]; then
  artifact_root="$repo_root/$artifact_root"
fi

run_id=${GITHUB_RUN_ID:-${CI_PIPELINE_ID:-$$}}
run_attempt=${GITHUB_RUN_ATTEMPT:-${CI_JOB_ID:-1}}
default_project="ntoj-deploy-${run_id}-${run_attempt}"
project_name=${NTOJ_E2E_PROJECT_NAME:-$default_project}
project_name=$(printf '%s' "$project_name" | tr '[:upper:]' '[:lower:]' | tr -cs 'a-z0-9_-' '-' | cut -c1-55)
project_name=${project_name%-}
if [[ ! "$project_name" =~ ^[a-z0-9][a-z0-9_-]*$ ]]; then
  echo "Unable to derive a valid Compose project name: $project_name" >&2
  exit 2
fi

# Coverage and Playwright outputs are serialized by run-coverage.sh, but the
# deployment wrapper can still be invoked concurrently. Keep diagnostics and
# exit statuses isolated per Compose project so a lock-rejected run cannot
# overwrite the active run's evidence.
artifact_dir="$artifact_root/$project_name"
mkdir -p "$artifact_dir"
rm -f "$artifact_dir/status.txt" "$artifact_dir/cleanup-check.txt" "$artifact_dir/coverage-status.txt"

for required_command in docker flock git; do
  if ! command -v "$required_command" >/dev/null 2>&1; then
    echo "Missing deployment-test prerequisite: $required_command" >&2
    exit 127
  fi
done
if ! docker compose version >/dev/null 2>&1; then
  echo "Docker Compose v2 is required." >&2
  exit 127
fi
if ! docker info >/dev/null 2>&1; then
  echo "The deployment-test user cannot access the Docker daemon." >&2
  exit 1
fi
if [[ "$(docker info --format '{{.OSType}}')" != linux ]]; then
  echo "The privileged Judge requires a Linux Docker daemon." >&2
  exit 1
fi
if [[ ! -d /sys/fs/cgroup ]]; then
  echo "The privileged Judge requires the host cgroup filesystem." >&2
  exit 1
fi

export NTOJ_E2E_PROJECT_NAME="$project_name"
export NTOJ_INTEGRATION_PROJECT_NAME="${project_name}-integration"
export NTOJ_E2E_KEEP_ENVIRONMENT=0
export NTOJ_E2E_START_UI=0
export NTOJ_E2E_SERVE_COVERAGE=0
export NTOJ_E2E_PORT=${NTOJ_E2E_PORT:-0}
export NTOJ_E2E_UI_PORT=${NTOJ_E2E_UI_PORT:-0}
export NTOJ_E2E_COVERAGE_PORT=${NTOJ_E2E_COVERAGE_PORT:-0}
export NTOJ_E2E_LOG_DIR="$artifact_dir"
export NTOJ_PYTHON_COVERAGE_MIN=${NTOJ_PYTHON_COVERAGE_MIN:-100}

started_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)
{
  printf 'started_at=%s\n' "$started_at"
  printf 'git_commit=%s\n' "$(git rev-parse HEAD)"
  printf 'project_name=%s\n' "$NTOJ_E2E_PROJECT_NAME"
  printf 'python_coverage_min=%s\n' "$NTOJ_PYTHON_COVERAGE_MIN"
  printf 'docker_server=%s\n' "$(docker version --format '{{.Server.Version}}')"
  printf 'docker_compose=%s\n' "$(docker compose version --short)"
  printf 'kernel=%s\n' "$(uname -srmo)"
} >"$artifact_dir/preflight.txt"

set +e
bash src/tests/e2e/run-coverage.sh
workflow_status=$?
set -e

# Retry teardown from the outer deployment wrapper and verify that the unique
# project did not leak resources even if the inner shell was interrupted.
cleanup_status=0
docker compose \
  -p "$NTOJ_E2E_PROJECT_NAME" \
  -f src/tests/e2e/docker-compose.yml \
  -f src/tests/e2e/docker-compose.node.yml \
  -f src/tests/e2e/docker-compose.coverage.yml \
  --profile judge down -v --remove-orphans >/dev/null 2>&1 || cleanup_status=$?
docker compose \
  -p "$NTOJ_INTEGRATION_PROJECT_NAME" \
  -f src/tests/e2e/docker-compose.yml \
  --profile judge down -v --remove-orphans >/dev/null 2>&1 || cleanup_status=$?

remaining_containers=$(
  docker ps -aq --filter "label=com.docker.compose.project=$NTOJ_E2E_PROJECT_NAME"
  docker ps -aq --filter "label=com.docker.compose.project=$NTOJ_INTEGRATION_PROJECT_NAME"
)
remaining_volumes=$(
  docker volume ls -q --filter "label=com.docker.compose.project=$NTOJ_E2E_PROJECT_NAME"
  docker volume ls -q --filter "label=com.docker.compose.project=$NTOJ_INTEGRATION_PROJECT_NAME"
)
remaining_networks=$(
  docker network ls -q --filter "label=com.docker.compose.project=$NTOJ_E2E_PROJECT_NAME"
  docker network ls -q --filter "label=com.docker.compose.project=$NTOJ_INTEGRATION_PROJECT_NAME"
)
{
  printf 'cleanup_exit_code=%s\n' "$cleanup_status"
  printf 'remaining_containers=%s\n' "$remaining_containers"
  printf 'remaining_volumes=%s\n' "$remaining_volumes"
  printf 'remaining_networks=%s\n' "$remaining_networks"
} >"$artifact_dir/cleanup-check.txt"
if (( cleanup_status != 0 )) || [[ -n "$remaining_containers$remaining_volumes$remaining_networks" ]]; then
  echo "Deployment test resources were not completely removed." >&2
  if (( workflow_status == 0 )); then
    workflow_status=70
  fi
fi

finished_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)
{
  printf 'started_at=%s\n' "$started_at"
  printf 'finished_at=%s\n' "$finished_at"
  printf 'exit_code=%s\n' "$workflow_status"
  printf 'project_name=%s\n' "$NTOJ_E2E_PROJECT_NAME"
  printf 'python_coverage_min=%s\n' "$NTOJ_PYTHON_COVERAGE_MIN"
} >"$artifact_dir/status.txt"

if (( workflow_status == 0 )); then
  echo "Deployment test gate passed."
else
  echo "Deployment test gate failed with exit code $workflow_status." >&2
fi
artifact_display=${artifact_dir#"$repo_root/"}
echo "Artifacts: $artifact_display, src/tests/e2e/node/playwright-report, src/tests/e2e/node/test-results, src/tests/e2e/coverage"
exit "$workflow_status"
