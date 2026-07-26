import json
import os
import re
import sys
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from app import create_app  # noqa: E402

# A separate database so that running the suite never touches dev data.
TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+psycopg://taskapi:taskapi@127.0.0.1:5432/taskapi_test",
)


@pytest.fixture(scope="session")
def app():
    """Application bound to the test database, with migrations applied.

    Running the real migrations rather than ``Base.metadata.create_all`` means
    a broken migration fails the suite instead of reaching production.
    """
    config = Config(str(BACKEND / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND / "alembic"))
    config.set_main_option("sqlalchemy.url", TEST_DATABASE_URL)
    command.upgrade(config, "head")

    application = create_app(TEST_DATABASE_URL)
    application.config["TESTING"] = True
    return application


@pytest.fixture(autouse=True)
def clean_tables(app):
    """Empty the tables and reset the id sequence before each test.

    request_metrics is truncated too: every test request runs through the
    real after_request hook, so leftover counts from an earlier test would
    otherwise leak into whichever test checks /metrics/summary.
    """
    with app.extensions["engine"].begin() as connection:
        connection.execute(text("TRUNCATE tasks RESTART IDENTITY CASCADE"))
        connection.execute(text("TRUNCATE request_metrics"))
    yield


@pytest.fixture()
def client(app):
    with app.test_client() as client:
        yield client


# --- behaviour -------------------------------------------------------------


def test_create_read_update_delete_task(client):
    response = client.post("/tasks", json={"title": "Buy milk"})
    assert response.status_code == 201
    created = response.get_json()
    assert created["title"] == "Buy milk"
    assert created["finished"] is False

    task_id = created["id"]

    response = client.get(f"/tasks/{task_id}")
    assert response.status_code == 200
    assert response.get_json()["title"] == "Buy milk"

    response = client.put(f"/tasks/{task_id}", json={"finished": True})
    assert response.status_code == 200
    assert response.get_json()["finished"] is True

    response = client.delete(f"/tasks/{task_id}")
    assert response.status_code == 200
    assert response.get_json()["message"] == "Task deleted"

    response = client.get(f"/tasks/{task_id}")
    assert response.status_code == 404


def test_tasks_are_persisted_across_requests(client):
    """The store is a database now, not per-process state."""
    for title in ("first", "second", "third"):
        assert client.post("/tasks", json={"title": title}).status_code == 201

    listed = client.get("/tasks").get_json()
    assert [task["title"] for task in listed] == ["first", "second", "third"]


def test_list_order_is_stable_after_an_update(client):
    """Postgres may relocate an updated row; ORDER BY keeps the list stable."""
    ids = [client.post("/tasks", json={"title": t}).get_json()["id"] for t in "abc"]

    client.put(f"/tasks/{ids[0]}", json={"finished": True})
    client.put(f"/tasks/{ids[1]}", json={"title": "updated"})

    listed = client.get("/tasks").get_json()
    assert [task["id"] for task in listed] == ids


def test_validation_and_missing_tasks(client):
    assert client.post("/tasks", json={"title": "   "}).status_code == 422
    assert client.post("/tasks").status_code == 422
    assert client.put("/tasks/999", json={"finished": True}).status_code == 404
    assert client.delete("/tasks/999").status_code == 404

    created = client.post("/tasks", json={"title": "x"}).get_json()
    # A body-less PUT is rejected rather than silently succeeding as a no-op.
    assert client.put(f"/tasks/{created['id']}").status_code == 422
    # "yes" is not a JSON boolean, whatever marshmallow's defaults allow.
    assert client.put(f"/tasks/{created['id']}", json={"finished": "yes"}).status_code == 422


def test_routing_errors_return_json(client):
    """Errors that never reach a view must still be JSON, not Werkzeug HTML."""
    for response in (client.get("/tasks/abc"), client.patch("/tasks/1")):
        assert response.status_code in (404, 405)
        assert response.is_json


def test_health_endpoints(client):
    liveness = client.get("/healthz")
    assert liveness.status_code == 200
    assert liveness.get_json()["status"] == "ok"

    readiness = client.get("/readyz")
    assert readiness.status_code == 200
    assert readiness.get_json()["status"] == "ready"


def test_readiness_reports_503_when_the_database_is_unreachable(app):
    """A dead database must fail readiness, not liveness."""
    broken = create_app("postgresql+psycopg://taskapi:taskapi@127.0.0.1:1/nope")
    with broken.test_client() as client:
        assert client.get("/healthz").status_code == 200
        assert client.get("/readyz").status_code == 503


# --- request metrics --------------------------------------------------------


def test_metrics_summary_counts_requests_by_status_class(client):
    client.get("/tasks")
    client.get("/tasks")
    client.get("/tasks/999")  # 404

    summary = client.get("/metrics/summary").get_json()
    assert summary["total_requests"] == 3
    assert summary["total_errors"] == 1
    assert summary["error_rate"] == pytest.approx(1 / 3, abs=1e-4)

    # Summed across buckets, not indexed by buckets[0]: the 3 requests could
    # straddle a minute boundary and land in two buckets, depending on when
    # the test happens to run.
    assert sum(b["count"] for b in summary["buckets"]) == 3
    assert sum(b["errors"] for b in summary["buckets"]) == 1
    assert all(b["avg_duration_ms"] >= 0 for b in summary["buckets"])


def test_metrics_summary_excludes_health_checks_and_itself(client):
    """Otherwise Render's health-check polling would dominate the numbers."""
    client.get("/healthz")
    client.get("/readyz")
    client.get("/metrics/summary")

    summary = client.get("/metrics/summary").get_json()
    assert summary["total_requests"] == 0


def test_metrics_summary_window_is_clamped(client):
    """A caller can't ask for an unbounded window and force a huge scan."""
    client.get("/tasks")

    summary = client.get("/metrics/summary?minutes=999999").get_json()
    assert summary["window_minutes"] == 24 * 60


def test_connection_urls_are_rewritten_to_the_psycopg_driver():
    """Hosted providers hand out driver-less URLs; SQLAlchemy would pick psycopg2.

    This is the exact failure that broke the first Render deploy:
    ModuleNotFoundError: No module named 'psycopg2'.
    """
    from db import normalise_driver

    neon = "postgresql://u:p@ep-x.aws.neon.tech/neondb?sslmode=require"
    assert normalise_driver(neon) == (
        "postgresql+psycopg://u:p@ep-x.aws.neon.tech/neondb?sslmode=require"
    )

    # Heroku-style legacy scheme, which SQLAlchemy rejects outright.
    assert normalise_driver("postgres://u:p@h/db") == "postgresql+psycopg://u:p@h/db"

    # An explicit driver is left alone.
    already = "postgresql+psycopg://u:p@h/db"
    assert normalise_driver(already) == already


# --- OpenAPI document ------------------------------------------------------


def test_openapi_spec_is_served(client):
    response = client.get("/openapi.json")
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["openapi"] == "3.0.3"
    assert "/tasks" in payload["paths"]
    assert "/tasks/{task_id}" in payload["paths"]


def test_spec_is_a_valid_openapi_document(client):
    from openapi_spec_validator import validate

    validate(client.get("/openapi.json").get_json())


# --- spec/implementation drift guards --------------------------------------

# Endpoints that are not part of the API surface: static assets, the docs
# endpoints themselves, and the demo front-end page.
UNDOCUMENTED_ENDPOINTS = {
    "static",
    "index",
    "dashboard",
    "healthz",
    "readyz",
    "metrics_summary",
    "api-docs.openapi_json",
    "api-docs.openapi_swagger_ui",
}

PATH_PARAM_RE = re.compile(r"<(?:[^:<>]+:)?([^<>]+)>")

HTTP_METHODS = {"get", "put", "post", "delete", "patch", "head", "options", "trace"}


def _rule_to_openapi_path(rule: str) -> str:
    """Turn a Werkzeug rule (/tasks/<int:task_id>) into an OpenAPI path."""
    return PATH_PARAM_RE.sub(r"{\1}", rule)


def test_every_route_is_documented(app, client):
    """Catch routes added outside the Blueprint, which the generator can't see."""
    spec = client.get("/openapi.json").get_json()

    for rule in app.url_map.iter_rules():
        if rule.endpoint in UNDOCUMENTED_ENDPOINTS:
            continue
        path = _rule_to_openapi_path(rule.rule)
        assert path in spec["paths"], f"{path} is routed but missing from the spec"

        documented = set(spec["paths"][path])
        for method in rule.methods - {"HEAD", "OPTIONS"}:
            assert method.lower() in documented, f"{method} {path} is routed but undocumented"


def test_documented_paths_all_exist(app, client):
    """Catch the reverse: spec entries with no corresponding route."""
    spec = client.get("/openapi.json").get_json()
    routed = {_rule_to_openapi_path(rule.rule) for rule in app.url_map.iter_rules()}

    for path in spec["paths"]:
        assert path in routed, f"{path} is documented but not routed"


def test_error_responses_document_a_body(client):
    """A bare description is not enough — codegen needs a typed error model."""
    spec = client.get("/openapi.json").get_json()
    for path, operations in spec["paths"].items():
        for method, operation in operations.items():
            if method not in HTTP_METHODS:
                continue
            for status, response in operation["responses"].items():
                if not status.startswith(("4", "5")):
                    continue
                assert "content" in response, (
                    f"{method.upper()} {path} -> {status} documents no response body"
                )


def test_spec_on_disk_matches_the_generated_one(client):
    """openapi.json is a build artifact; fail if it was not regenerated."""
    on_disk = json.loads((BACKEND / "openapi.json").read_text())
    assert on_disk == client.get("/openapi.json").get_json(), (
        "openapi.json is stale — regenerate with: python app.py --dump-openapi"
    )


def test_every_operation_has_an_operation_id(client):
    """Client codegen produces mangled names without these."""
    spec = client.get("/openapi.json").get_json()
    for path, operations in spec["paths"].items():
        for method, operation in operations.items():
            if method not in HTTP_METHODS:  # e.g. path-level "parameters"
                continue
            assert "operationId" in operation, f"{method.upper()} {path} has no operationId"
