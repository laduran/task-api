import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

import db  # noqa: E402
from app import create_app  # noqa: E402
from models import User  # noqa: E402

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

    users is truncated in the same statement as tasks (which references it
    via owner_id) so Postgres handles the FK ordering in one go.
    """
    with app.extensions["engine"].begin() as connection:
        connection.execute(text("TRUNCATE tasks, users RESTART IDENTITY CASCADE"))
    yield


def _create_user(app, *, google_sub: str, email: str) -> int:
    """Insert a user directly, bypassing the real Google OAuth handshake.

    Exercising /auth/login or /auth/google/callback in tests would require a
    live network call to Google's OIDC metadata endpoint (Authlib fetches it
    lazily, only when those routes actually run) — not something the test
    suite should depend on. Everything reachable without that network call —
    the upsert logic, the login-required gate, session handling — is tested
    directly instead; the real handshake is verified once by hand in a
    browser, against real Google credentials.
    """
    with app.app_context():
        session = db.session()
        user = User(
            google_sub=google_sub,
            email=email,
            name=f"Test User ({email})",
            picture_url=None,
            created_at=datetime.now(timezone.utc),
        )
        session.add(user)
        session.commit()
        return user.id


@pytest.fixture()
def user_id(app, clean_tables):
    return _create_user(app, google_sub="test-sub-1", email="test1@example.com")


@pytest.fixture()
def client(app, user_id):
    """A signed-in test client — what most tests want, since /tasks now
    requires a session. Tests of the auth boundary itself use anon_client.

    Deliberately not `with app.test_client() as client: yield client`: two
    such context-managed clients coexisting in one test (several auth tests
    need exactly that, to compare a signed-in and an anonymous view) corrupts
    Flask's request-context stack on teardown. The plain form doesn't have
    that failure mode, and session_transaction() works fine without it.
    """
    client = app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = user_id
    return client


@pytest.fixture()
def anon_client(app, clean_tables):
    """A test client with no session at all."""
    return app.test_client()


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


# --- auth --------------------------------------------------------------------


def test_tasks_require_login(anon_client):
    assert anon_client.get("/tasks").status_code == 401
    assert anon_client.post("/tasks", json={"title": "x"}).status_code == 401
    assert anon_client.get("/tasks/1").status_code == 401
    assert anon_client.put("/tasks/1", json={"finished": True}).status_code == 401
    assert anon_client.delete("/tasks/1").status_code == 401

    # Still a proper JSON error, not a bare redirect or an HTML page.
    response = anon_client.get("/tasks")
    assert response.is_json
    assert "message" in response.get_json()


def test_public_endpoints_do_not_require_login(anon_client):
    """The auth gate is scoped to the tasks Blueprint, not the whole app."""
    for path in (
        "/", "/healthz", "/readyz", "/auth/me", "/favicon.ico",
    ):
        assert anon_client.get(path).status_code == 200, path


def test_auth_me_reports_signed_in_state(client, anon_client):
    assert anon_client.get("/auth/me").get_json() == {"authenticated": False}

    me = client.get("/auth/me").get_json()
    assert me["authenticated"] is True
    assert me["email"] == "test1@example.com"
    assert me["name"]


def test_logout_clears_the_session(client):
    assert client.get("/tasks").status_code == 200
    # A plain <form method=post> target, so it redirects rather than
    # returning JSON — no fetch() needed on the frontend.
    logout = client.post("/auth/logout")
    assert logout.status_code == 302
    assert logout.location == "/"
    assert client.get("/tasks").status_code == 401


def test_tasks_are_isolated_between_users(app, client):
    """A task belonging to another user is invisible, not merely forbidden."""
    created = client.post("/tasks", json={"title": "mine"}).get_json()

    other_user_id = _create_user(app, google_sub="test-sub-2", email="test2@example.com")
    other_client = app.test_client()
    with other_client.session_transaction() as sess:
        sess["user_id"] = other_user_id

    assert other_client.get("/tasks").get_json() == []
    # 404, not 403 — a 403 would confirm the id belongs to *someone*.
    assert other_client.get(f"/tasks/{created['id']}").status_code == 404
    assert other_client.put(f"/tasks/{created['id']}", json={"finished": True}).status_code == 404
    assert other_client.delete(f"/tasks/{created['id']}").status_code == 404

    # Untouched from the owner's side.
    assert client.get(f"/tasks/{created['id']}").status_code == 200


def test_upsert_user_creates_then_updates_on_second_login(app):
    """The second login for the same Google account updates the row in place
    rather than creating a duplicate — this is the actual logic behind the
    OAuth callback, tested directly since the callback itself needs a live
    network call to Google to exercise end-to-end."""
    import auth

    with app.app_context():
        first = auth._upsert_user(
            {"sub": "stable-id", "email": "old@example.com", "name": "Old Name"}
        )
        assert first.email == "old@example.com"

        second = auth._upsert_user(
            {"sub": "stable-id", "email": "new@example.com", "name": "New Name", "picture": "http://x/p.png"}
        )
        assert second.id == first.id
        assert second.email == "new@example.com"
        assert second.name == "New Name"
        assert second.picture_url == "http://x/p.png"


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
    "favicon",
    "healthz",
    "readyz",
    "auth_login",
    "auth_callback",
    "auth_logout",
    "auth_me",
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
