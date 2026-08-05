#!/usr/bin/env bash
set -euo pipefail

scenario=${1:-public-read}
script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
results_dir=${RESULTS_DIR:-"$script_dir/results"}
k6_image=${K6_IMAGE:-grafana/k6:2.0.0}
base_url=${BASE_URL:-http://127.0.0.1:5500}

if [[ "${CONFIRM_ISOLATED:-false}" != "true" && "$base_url" != http://127.0.0.1:* && "$base_url" != http://localhost:* && "$base_url" != http://host.docker.internal:* ]]; then
  echo "Refusing to load-test a remote target without CONFIRM_ISOLATED=true" >&2
  exit 2
fi

case "$scenario" in
  public-read)
    script_name=public-read.js
    ;;
  judge-submit)
    if [[ "${CONFIRM_JUDGE_STRESS:-false}" != "true" ]]; then
      echo "Judge submission stress requires CONFIRM_JUDGE_STRESS=true" >&2
      exit 2
    fi
    script_name=judge-submit.js
    ;;
  oj-mixed)
    if [[ "${CONFIRM_JUDGE_STRESS:-false}" != "true" ]]; then
      echo "Mixed OJ stress requires CONFIRM_JUDGE_STRESS=true" >&2
      exit 2
    fi
    script_name=oj-mixed.js
    ;;
  *)
    echo "Unknown stress scenario: $scenario" >&2
    exit 2
    ;;
esac

mkdir -p "$results_dir"
results_dir=$(cd -- "$results_dir" && pwd)
safe_run_id=${STRESS_RUN_ID:-}
safe_run_id=${safe_run_id//[^[:alnum:]_.-]/_}
summary_suffix=${safe_run_id:+-$safe_run_id}

docker run --rm \
  --user "$(id -u):$(id -g)" \
  --add-host host.docker.internal:host-gateway \
  --env BASE_URL \
  --env VUS \
  --env DURATION \
  --env REQUEST_SLEEP \
  --env RATE \
  --env TOTAL_SUBMISSIONS \
  --env MAX_DURATION \
  --env PRE_ALLOCATED_VUS \
  --env MAX_VUS \
  --env PROBLEM_ID \
  --env NORMAL_USER_VUS \
  --env NORMAL_SUBMISSIONS_PER_USER \
  --env NORMAL_USER_SLEEP \
  --env CONTEST_USER_VUS \
  --env CONTEST_COUNT \
  --env CONTEST_COOLDOWN_SECONDS \
  --env CONTEST_USER_SLEEP \
  --env REJUDGE_RATE \
  --env REJUDGE_TARGET_COUNT \
  --env SCOREBOARD_RATE \
  --env SCOREBOARD_MAX_VUS \
  --env WORKLOAD_START_TIME \
  --env REJUDGE_START_TIME \
  --env SETUP_TIMEOUT \
  --env STRESS_RUN_ID \
  --env STRESS_USER_PASSWORD \
  --env STRESS_ADMIN_EMAIL \
  --env STRESS_ADMIN_PASSWORD \
  --env CONFIRM_JUDGE_STRESS \
  --volume "$script_dir/k6:/scripts:ro" \
  --volume "$results_dir:/results" \
  "$k6_image" run \
  --summary-export="/results/$scenario$summary_suffix-summary.json" \
  "/scripts/$script_name"
