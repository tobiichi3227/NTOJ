#!/usr/bin/env bash
set -euo pipefail

service=${1:-}
duration=${2:-10}

if [[ "${CONFIRM_ISOLATED:-false}" != "true" ]]; then
  echo "Fault injection requires CONFIRM_ISOLATED=true" >&2
  exit 2
fi

case "$service" in
  judge|cache|db) ;;
  *)
    echo "Service must be one of: judge, cache, db" >&2
    exit 2
    ;;
esac

if ! [[ "$duration" =~ ^[0-9]+$ ]] || (( duration < 1 || duration > 30 )); then
  echo "Duration must be an integer from 1 to 30 seconds" >&2
  exit 2
fi

compose=(docker compose -f docker-compose.dev.yml)
restore_service() {
  "${compose[@]}" unpause "$service" >/dev/null 2>&1 || true
}
trap restore_service EXIT INT TERM

"${compose[@]}" pause "$service"
sleep "$duration"
restore_service
trap - EXIT INT TERM
