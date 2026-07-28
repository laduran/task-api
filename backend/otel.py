"""OpenTelemetry wiring: request traces, DB spans, and HTTP metrics exported
over OTLP to whatever OTEL_EXPORTER_OTLP_ENDPOINT points at (Grafana Cloud's
OTLP gateway, in production).

Standard OTel env vars configure everything else -- OTEL_EXPORTER_OTLP_HEADERS
for the auth token, OTEL_SERVICE_NAME for the service name -- so there is
nothing OTel-specific to plumb through Flask config, unlike DATABASE_URL and
friends in app.py. The exporters read those env vars themselves when
constructed with no arguments.

A missing OTEL_EXPORTER_OTLP_ENDPOINT means "not configured" (local dev, CI,
tests): init_app becomes a no-op rather than exporting to nowhere or slowing
down every request with doomed export attempts.
"""

from __future__ import annotations

import logging
import os

from flask import Flask

_log = logging.getLogger(__name__)

# create_app() runs more than once in the same process (the module-level
# `app = create_app()` in app.py, then again on the --dump-openapi path) --
# the OTel SDK's global providers can only be set once, so a second call
# would leave an extra, detached exporter/processor set that never gets used
# or shut down. This makes init_app idempotent instead.
_initialized = False


def init_app(app: Flask) -> None:
    global _initialized
    if not os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT") or _initialized:
        return

    # Imported lazily: these packages (and their transitive dependencies)
    # have no reason to load, or even be installed as more than an unused
    # extra, in an environment that never sets the endpoint.
    from opentelemetry import metrics, trace
    from opentelemetry.exporter.otlp.proto.http.metric_exporter import (
        OTLPMetricExporter,
    )
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
        OTLPSpanExporter,
    )
    from opentelemetry.instrumentation.flask import FlaskInstrumentor
    from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
    from opentelemetry.sdk.metrics import MeterProvider
    from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    resource = Resource.create(
        {"service.name": os.environ.get("OTEL_SERVICE_NAME", "task-api")}
    )

    tracer_provider = TracerProvider(resource=resource)
    # Batched and exported on a background thread, so a slow or unreachable
    # collector delays telemetry, never a response.
    tracer_provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
    trace.set_tracer_provider(tracer_provider)

    meter_provider = MeterProvider(
        resource=resource,
        metric_readers=[PeriodicExportingMetricReader(OTLPMetricExporter())],
    )
    metrics.set_meter_provider(meter_provider)

    FlaskInstrumentor().instrument_app(app)
    # Needs the engine directly (not just the Flask app) to hook SQLAlchemy's
    # own event system; db.init_app must already have run by this point.
    SQLAlchemyInstrumentor().instrument(engine=app.extensions["engine"])

    # Only marked done once every step above has actually succeeded, so a
    # failure here (bad env var, exporter construction error) leaves
    # _initialized False and a later create_app() call in the same process
    # can retry instead of silently no-op'ing forever. Note this can't undo
    # a set_tracer_provider()/set_meter_provider() call that already
    # succeeded before a later step failed -- OTel's global providers are
    # one-shot by design (see set_tracer_provider's own warning, reproduced
    # by the double-init this flag guards against) and expose no public
    # "unset". A retry after a partial failure would hit "Overriding
    # of current ... is not allowed" rather than a clean re-init; accepted
    # as a known limitation rather than worked around with private API.
    _initialized = True


def shutdown() -> None:
    """Flush any buffered spans/metrics before the process exits.

    Without this, telemetry from the final seconds before a deploy or
    restart can be lost -- the batch processor exports on a timer, not
    immediately.
    """
    if not _initialized:
        return

    from opentelemetry import metrics, trace

    # Independent try/excepts: a failure flushing traces should not prevent
    # metrics from getting their own chance to flush, and vice versa.
    tracer_provider = trace.get_tracer_provider()
    if hasattr(tracer_provider, "shutdown"):
        try:
            tracer_provider.shutdown()
        except Exception:
            _log.warning("failed to shut down OTel tracer provider", exc_info=True)

    meter_provider = metrics.get_meter_provider()
    if hasattr(meter_provider, "shutdown"):
        try:
            meter_provider.shutdown()
        except Exception:
            _log.warning("failed to shut down OTel meter provider", exc_info=True)
