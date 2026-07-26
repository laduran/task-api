"""Minimal request metrics: golden signals with no external service.

Every request is aggregated into a per-minute, per-status-class counter in
Postgres (the same database the app already has) and read back by
``GET /metrics/summary`` for the dashboard page. This exists instead of
wiring up Grafana/Datadog/App Insights, which assume a team consuming
alerts and bill per-host or per-GB — the wrong shape for a single free-tier
service. It also doesn't lean on Render's own HTTP metrics: those returned
empty in testing against this service's free plan even immediately after
real traffic, while CPU/memory metrics on the same API worked fine.
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from typing import Any

from flask import Flask, g, request
from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import SQLAlchemyError

import db
from models import RequestMetric

# Infra probes and the metrics endpoint itself: excluded so the dashboard
# doesn't measure its own polling or Render's health checks.
_EXCLUDED_PATHS = {"/healthz", "/readyz", "/metrics/summary"}

_MAX_WINDOW_MINUTES = 24 * 60

# Recording runs synchronously in after_request, on the critical path of
# every response. A hung connection or a stalled statement would otherwise
# block that response indefinitely; this bounds it to the same transaction
# only, via SET LOCAL, so it can't affect any query outside _upsert.
_WRITE_TIMEOUT = "SET LOCAL statement_timeout = '2000ms'"


def _status_class(status_code: int) -> str:
    return f"{status_code // 100}xx"


def init_app(app: Flask) -> None:
    """Register before/after hooks that record every request."""

    @app.before_request
    def _start_timer() -> None:
        g.metrics_start = time.perf_counter()

    @app.after_request
    def _record(response):
        if request.path in _EXCLUDED_PATHS or request.path.startswith("/static/"):
            return response
        start = g.pop("metrics_start", None)
        if start is None:
            return response

        duration_ms = int((time.perf_counter() - start) * 1000)
        minute = datetime.now(timezone.utc).replace(second=0, microsecond=0)
        try:
            _upsert(minute, _status_class(response.status_code), duration_ms)
        except SQLAlchemyError as exc:
            # A metrics-write failure must never turn a good response into a
            # 500 — it's observability, not the feature.
            db.session().rollback()
            app.logger.warning("failed to record request metric: %s", exc)
        return response


def _upsert(minute: datetime, status_class: str, duration_ms: int) -> None:
    session = db.session()
    session.execute(text(_WRITE_TIMEOUT))
    insert_stmt = insert(RequestMetric).values(
        minute=minute,
        status_class=status_class,
        count=1,
        total_duration_ms=duration_ms,
        max_duration_ms=duration_ms,
    )
    stmt = insert_stmt.on_conflict_do_update(
        index_elements=[RequestMetric.minute, RequestMetric.status_class],
        set_={
            "count": RequestMetric.count + insert_stmt.excluded.count,
            "total_duration_ms": RequestMetric.total_duration_ms + insert_stmt.excluded.total_duration_ms,
            "max_duration_ms": func.greatest(
                RequestMetric.max_duration_ms, insert_stmt.excluded.max_duration_ms
            ),
        },
    )
    session.execute(stmt)
    session.commit()


def summary(minutes: int = 60) -> dict[str, Any]:
    """Aggregate recorded requests over the trailing *minutes* window."""
    minutes = max(1, min(minutes, _MAX_WINDOW_MINUTES))
    since = datetime.now(timezone.utc) - timedelta(minutes=minutes)

    session = db.session()
    rows = session.execute(
        select(
            RequestMetric.minute,
            RequestMetric.status_class,
            RequestMetric.count,
            RequestMetric.total_duration_ms,
            RequestMetric.max_duration_ms,
        )
        .where(RequestMetric.minute >= since)
        .order_by(RequestMetric.minute)
    ).all()

    buckets: dict[str, dict[str, Any]] = {}
    for minute, status_class, count, total_ms, max_ms in rows:
        key = minute.isoformat()
        bucket = buckets.setdefault(
            key,
            {"minute": key, "count": 0, "errors": 0, "total_duration_ms": 0, "max_duration_ms": 0},
        )
        bucket["count"] += count
        if status_class in ("4xx", "5xx"):
            bucket["errors"] += count
        bucket["total_duration_ms"] += total_ms
        bucket["max_duration_ms"] = max(bucket["max_duration_ms"], max_ms)

    ordered = [buckets[key] for key in sorted(buckets)]
    for bucket in ordered:
        bucket["avg_duration_ms"] = (
            round(bucket["total_duration_ms"] / bucket["count"], 1) if bucket["count"] else 0.0
        )

    total_requests = sum(bucket["count"] for bucket in ordered)
    total_errors = sum(bucket["errors"] for bucket in ordered)

    return {
        "window_minutes": minutes,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_requests": total_requests,
        "total_errors": total_errors,
        "error_rate": round(total_errors / total_requests, 4) if total_requests else 0.0,
        "buckets": ordered,
    }
