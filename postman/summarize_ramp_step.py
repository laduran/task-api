#!/usr/bin/env python3
"""Aggregates one ramp step's Newman JSON reporter exports.

Reads every worker-*.json in the given directory and prints three
space-separated numbers: total requests, failed assertions, weighted average
response time (ms). Used by run-ramp-load.sh to decide when the failure rate
crosses its stop threshold.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path


def main() -> None:
    step_dir = Path(sys.argv[1])

    total_requests = 0
    total_failed_assertions = 0
    response_time_weighted_sum = 0.0

    for report_path in sorted(step_dir.glob("worker-*.json")):
        data = json.loads(report_path.read_text())
        stats = data["run"]["stats"]
        timings = data["run"]["timings"]

        worker_requests = stats["requests"]["total"]
        total_requests += worker_requests
        total_failed_assertions += stats["assertions"]["failed"]
        response_time_weighted_sum += timings.get("responseAverage", 0) * worker_requests

    avg_ms = round(response_time_weighted_sum / total_requests) if total_requests else 0
    print(total_requests, total_failed_assertions, avg_ms)


if __name__ == "__main__":
    main()
