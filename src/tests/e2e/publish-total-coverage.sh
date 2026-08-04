#!/bin/bash

set -euo pipefail

cd "$(dirname "$0")/../../.."

project_name=${NTOJ_E2E_PROJECT_NAME:-ntoj-e2e}
serve_coverage=${NTOJ_E2E_SERVE_COVERAGE:-1}
coverage_min=${NTOJ_PYTHON_COVERAGE_MIN:-100}

if [[ "$serve_coverage" != 0 && "$serve_coverage" != 1 ]]; then
  echo "NTOJ_E2E_SERVE_COVERAGE must be 0 or 1" >&2
  exit 2
fi
if [[ ! "$coverage_min" =~ ^[0-9]+([.][0-9]+)?$ ]]; then
  echo "NTOJ_PYTHON_COVERAGE_MIN must be a non-negative number" >&2
  exit 2
fi

compose=(
  docker compose
  -p "$project_name"
  -f src/tests/e2e/docker-compose.yml
  -f src/tests/e2e/docker-compose.node.yml
  -f src/tests/e2e/docker-compose.coverage.yml
)

"${compose[@]}" build backend

"${compose[@]}" run --rm --no-deps \
  -e NTOJ_PYTHON_COVERAGE_MIN="$coverage_min" \
  --entrypoint bash backend -lc \
    'set -euo pipefail
     combine_root=/tmp/ntoj-coverage-combine
     rm -rf "$combine_root"
     mkdir -p "$combine_root"

     index=0
     found=0
     for suite_file in /coverage/python/suites/*/.coverage*; do
         if [[ ! -f "$suite_file" ]]; then
             continue
         fi
         cp "$suite_file" "$combine_root/.coverage.$index"
         index=$((index + 1))
         found=1
     done

     if (( found == 0 )); then
         echo "No suite coverage data found under /coverage/python/suites" >&2
         exit 2
     fi

     rm -f /coverage/python/.coverage /coverage/python/coverage.json
     rm -rf /coverage/python/html
     COVERAGE_FILE=/coverage/python/.coverage /root/.local/bin/poetry run coverage combine --keep --rcfile=/ntoj/tests/e2e/python-coveragerc "$combine_root"
     COVERAGE_FILE=/coverage/python/.coverage /root/.local/bin/poetry run coverage html --rcfile=/ntoj/tests/e2e/python-coveragerc
     COVERAGE_FILE=/coverage/python/.coverage /root/.local/bin/poetry run coverage json --rcfile=/ntoj/tests/e2e/python-coveragerc
     COVERAGE_FILE=/coverage/python/.coverage /root/.local/bin/poetry run coverage report --rcfile=/ntoj/tests/e2e/python-coveragerc --fail-under="$NTOJ_PYTHON_COVERAGE_MIN"
     /root/.local/bin/poetry run python /ntoj/tests/e2e/verify_python_coverage.py /coverage/python/coverage.json "$NTOJ_PYTHON_COVERAGE_MIN"'

"${compose[@]}" run --rm --no-deps \
  --volume "$PWD/src/tests/e2e/render_coverage_dashboard.py:/render_coverage_dashboard.py:ro" \
  --entrypoint python3 coverage-report /render_coverage_dashboard.py /coverage

if (( serve_coverage != 0 )); then
  "${compose[@]}" up -d coverage-report
  echo "Total coverage dashboard: http://127.0.0.1:${NTOJ_E2E_COVERAGE_PORT:-9325}"
else
  echo "Total coverage artifact: src/tests/e2e/coverage/index.html"
fi
