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

import os

from flask import Flask


def init_app(app: Flask) -> None:
    if not os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT"):
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


def shutdown() -> None:
    """Flush any buffered spans/metrics before the process exits.

    Without this, telemetry from the final seconds before a deploy or
    restart can be lost -- the batch processor exports on a timer, not
    immediately.
    """
    if not os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT"):
        return

    from opentelemetry import metrics, trace

    tracer_provider = trace.get_tracer_provider()
    if hasattr(tracer_provider, "shutdown"):
        tracer_provider.shutdown()

    meter_provider = metrics.get_meter_provider()
    if hasattr(meter_provider, "shutdown"):
        meter_provider.shutdown()
