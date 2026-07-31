#!/usr/bin/env bash
# Runs N concurrent Newman workers against the Stress Test collection to
# generate real concurrent load. Each worker is a separate OS process with
# its own copy of the collection's in-memory variables, so there's no
# cross-worker race on task_id/toggle_count/etc. like there would be with
# Postman's in-app Performance testing (shared virtual-user state).
set -euo pipefail

WORKERS="${1:-10}"
ITERATIONS="${2:-25}"
DELAY_MS="${3:-10}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COLLECTION="$SCRIPT_DIR/stress-test.postman_collection.json"
ENVIRONMENT="$SCRIPT_DIR/stress-test.postman_environment.json"
LOG_DIR="$SCRIPT_DIR/run-logs/$(date +%Y%m%d-%H%M%S)"
mkdir -p "$LOG_DIR"

echo "Launching $WORKERS concurrent Newman workers, $ITERATIONS iterations each, ${DELAY_MS}ms delay between requests..."
echo "Logs: $LOG_DIR"

pids=()
for i in $(seq 1 "$WORKERS"); do
  npx newman run "$COLLECTION" -e "$ENVIRONMENT" -n "$ITERATIONS" --delay-request "$DELAY_MS" \
    > "$LOG_DIR/worker-$i.log" 2>&1 &
  pids+=("$!")
done

fail=0
for pid in "${pids[@]}"; do
  wait "$pid" || fail=1
done

if [ "$fail" -ne 0 ]; then
  echo "One or more workers reported failures - check $LOG_DIR/worker-*.log"
  exit 1
fi

echo "All $WORKERS workers finished. Logs in $LOG_DIR"
