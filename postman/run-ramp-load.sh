#!/usr/bin/env bash
# Steps concurrency up in stages to find where task-api starts failing under
# load. Each step runs N concurrent Newman workers (separate processes, so no
# shared-state races) for a short fixed number of iterations, then aggregates
# pass/fail + average response time across all of them using Newman's own
# JSON reporter output. Stops automatically once a step's failure rate
# crosses FAIL_THRESHOLD_PCT.
#
# Why this matters here: backend/gunicorn.conf.py runs 4 sync workers with
# numInstances: 1 (see render.yaml) - only 4 requests can be processed
# concurrently on the whole service. Expect rising response times somewhere
# above 4 concurrent in-flight requests, and actual failures (timeouts /
# 502s from a wedged worker hitting the 30s gunicorn timeout) at some higher
# concurrency - that's the number this script is trying to locate.
set -euo pipefail

STEPS="${1:-1 2 4 8 16 32 64}"       # worker counts to try, in order
ITERATIONS="${2:-10}"                 # iterations per worker, per step
DELAY_MS="${3:-1}"                    # inter-request delay per worker (newman rejects 0)
FAIL_THRESHOLD_PCT="${4:-10}"         # stop ramping once failure rate exceeds this

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COLLECTION="$SCRIPT_DIR/stress-test.postman_collection.json"
LOCAL_ENVIRONMENT="$SCRIPT_DIR/stress-test.local.postman_environment.json"
ENVIRONMENT="$SCRIPT_DIR/stress-test.postman_environment.json"
if [ -f "$LOCAL_ENVIRONMENT" ]; then
  ENVIRONMENT="$LOCAL_ENVIRONMENT"
else
  echo "No $LOCAL_ENVIRONMENT found — using the tracked template, whose" \
       "session_cookie is blank. Every request will 401. See postman/README.md."
fi

RUN_DIR="$SCRIPT_DIR/run-logs/ramp-$(date +%Y%m%d-%H%M%S)"
mkdir -p "$RUN_DIR"

echo "Ramping concurrency: $STEPS"
echo "(iterations/worker=$ITERATIONS, delay=${DELAY_MS}ms, stop if failure rate > ${FAIL_THRESHOLD_PCT}%)"
echo "Logs: $RUN_DIR"
echo
printf "%-8s %-10s %-8s %-10s %s\n" "workers" "requests" "failed" "fail_pct" "avg_response_ms"

for workers in $STEPS; do
  STEP_DIR="$RUN_DIR/workers-$workers"
  mkdir -p "$STEP_DIR"

  pids=()
  for i in $(seq 1 "$workers"); do
    npx newman run "$COLLECTION" -e "$ENVIRONMENT" -n "$ITERATIONS" --delay-request "$DELAY_MS" \
      --reporters cli,json --reporter-json-export "$STEP_DIR/worker-$i.json" \
      > "$STEP_DIR/worker-$i.log" 2>&1 &
    pids+=("$!")
  done
  for pid in "${pids[@]}"; do
    wait "$pid" || true
  done

  read -r total failed avg_ms <<< "$(python3 "$SCRIPT_DIR/summarize_ramp_step.py" "$STEP_DIR")"
  fail_pct=$(python3 -c "print(round(100*$failed/$total, 1) if $total else 0)")

  printf "%-8s %-10s %-8s %-10s %s\n" "$workers" "$total" "$failed" "${fail_pct}%" "$avg_ms"

  if python3 -c "exit(0 if $fail_pct > $FAIL_THRESHOLD_PCT else 1)"; then
    echo
    echo "Failure rate exceeded ${FAIL_THRESHOLD_PCT}% at $workers concurrent workers — stopping ramp."
    break
  fi
done

echo
echo "Full per-worker logs and JSON reports: $RUN_DIR"
