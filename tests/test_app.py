import json
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import app, tasks


@pytest.fixture(autouse=True)
def clear_tasks():
    tasks.clear()
    import app as app_module

    app_module.next_id = 1
    yield
    tasks.clear()
    app_module.next_id = 1


@pytest.fixture()
def client():
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client


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


def test_openapi_spec_is_served(client):
    response = client.get("/openapi.json")
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["openapi"] == "3.0.3"
    assert "/tasks" in payload["paths"]
    assert "/tasks/{task_id}" in payload["paths"]


# --- spec/implementation drift guards -------------------------------------

# Endpoints that are not part of the API surface: static assets, the docs
# endpoints themselves, and the demo front-end page.
UNDOCUMENTED_ENDPOINTS = {
    "static",
    "index",
    "api-docs.openapi_json",
    "api-docs.openapi_swagger_ui",
}

PATH_PARAM_RE = re.compile(r"<(?:[^:<>]+:)?([^<>]+)>")

HTTP_METHODS = {"get", "put", "post", "delete", "patch", "head", "options", "trace"}


def _rule_to_openapi_path(rule: str) -> str:
    """Turn a Werkzeug rule (/tasks/<int:task_id>) into an OpenAPI path."""
    return PATH_PARAM_RE.sub(r"{\1}", rule)


def test_every_route_is_documented(client):
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


def test_documented_paths_all_exist(client):
    """Catch the reverse: spec entries with no corresponding route."""
    spec = client.get("/openapi.json").get_json()
    routed = {_rule_to_openapi_path(rule.rule) for rule in app.url_map.iter_rules()}

    for path in spec["paths"]:
        assert path in routed, f"{path} is documented but not routed"


def test_spec_is_a_valid_openapi_document(client):
    from openapi_spec_validator import validate

    validate(client.get("/openapi.json").get_json())


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
    on_disk = json.loads((Path(__file__).resolve().parents[1] / "openapi.json").read_text())
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
