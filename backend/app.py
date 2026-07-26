"""A small in-memory Task API.

The OpenAPI document is *derived* from the marshmallow schemas and the
registered Blueprint routes — it is never hand-written, so it cannot drift
away from the implementation. Serve it at ``/openapi.json`` or write it to
disk explicitly with ``python app.py --dump-openapi``.
"""

from __future__ import annotations

import threading
from typing import Any

from flask import Flask
from flask.views import MethodView
from flask_smorest import Api, Blueprint, abort
from marshmallow import Schema, ValidationError, fields, validate, validates_schema

# static/ lives at the project root, not under backend/: it is the handoff
# point between the two halves — the frontend build writes into it and the
# backend serves from it.
app = Flask(__name__, static_folder="../static", static_url_path="/static")

app.config["API_TITLE"] = "Task API"
app.config["API_VERSION"] = "1.0.0"
app.config["OPENAPI_VERSION"] = "3.0.3"
# Serve the generated document at /openapi.json and interactive docs at /docs.
app.config["OPENAPI_URL_PREFIX"] = "/"
app.config["OPENAPI_JSON_PATH"] = "openapi.json"
app.config["OPENAPI_SWAGGER_UI_PATH"] = "/docs"
app.config["OPENAPI_SWAGGER_UI_URL"] = "https://cdn.jsdelivr.net/npm/swagger-ui-dist/"
app.config["API_SPEC_OPTIONS"] = {
    "info": {
        "title": "Task API",
        "version": "1.0.0",
        "description": "A simple task management API with CRUD operations.",
    },
    "servers": [{"url": "/"}],
}

api = Api(app)

# In-memory store for tasks. `tasks` and `next_id` are module-level on purpose:
# tests reset them directly.
tasks: list[dict[str, Any]] = []
next_id = 1
_store_lock = threading.Lock()


def _not_blank(value: str) -> None:
    """Reject titles that are empty or only whitespace."""
    if not value.strip():
        raise ValidationError("Title must not be blank.")


class TaskSchema(Schema):
    """A task as returned by the API."""

    id = fields.Int(dump_only=True, metadata={"description": "Unique identifier.", "example": 1})
    title = fields.Str(required=True, metadata={"description": "What needs doing.", "example": "Buy milk"})
    finished = fields.Bool(metadata={"description": "Whether the task is complete.", "example": False})


class TaskCreateSchema(Schema):
    """Payload for creating a task."""

    title = fields.Str(
        required=True,
        validate=[validate.Length(min=1), _not_blank],
        metadata={"description": "What needs doing.", "example": "Buy milk"},
    )


class TaskUpdateSchema(Schema):
    """Payload for updating a task.

    Both fields are individually optional — only the supplied ones are
    modified — but at least one must be present, so that a body-less PUT is
    rejected rather than silently succeeding as a no-op.
    """

    title = fields.Str(
        validate=[validate.Length(min=1), _not_blank],
        metadata={"description": "New title.", "example": "Buy oat milk"},
    )
    finished = fields.Bool(
        # Restrict to real JSON booleans; marshmallow otherwise accepts
        # "yes"/"on"/1 and friends, which the documented type does not allow.
        truthy={True},
        falsy={False},
        metadata={"description": "New completion state.", "example": True},
    )

    @validates_schema
    def _require_at_least_one_field(self, data: dict[str, Any], **kwargs: Any) -> None:
        if not data:
            raise ValidationError("Supply at least one of 'title' or 'finished'.")


class DeleteResultSchema(Schema):
    """Confirmation returned when a task is deleted."""

    message = fields.Str(required=True, metadata={"example": "Task deleted"})


blp = Blueprint("tasks", __name__, description="Create, read, update and delete tasks.")

# Reuse flask-smorest's own error schema (the shape its error handler emits)
# rather than declaring our own, which would register a duplicate component.
ErrorSchema = Api.ERROR_SCHEMA


def _find_task_or_404(task_id: int) -> dict[str, Any]:
    task = next((task for task in tasks if task["id"] == task_id), None)
    if task is None:
        abort(404, message="Task not found")
    return task


@blp.route("/tasks")
class TaskCollection(MethodView):
    @blp.doc(operationId="listTasks", summary="List tasks")
    @blp.response(200, TaskSchema(many=True), description="Every task currently stored in memory.")
    def get(self) -> list[dict[str, Any]]:
        """Return every task currently stored in memory."""
        return tasks

    @blp.doc(operationId="createTask", summary="Create a task")
    @blp.arguments(TaskCreateSchema)
    @blp.response(201, TaskSchema, description="The newly created task.")
    @blp.alt_response(422, schema=ErrorSchema, description="The title is missing or blank.")
    def post(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Create a new task."""
        global next_id
        with _store_lock:
            task = {"id": next_id, "title": payload["title"].strip(), "finished": False}
            next_id += 1
            tasks.append(task)
        return task


@blp.route("/tasks/<int:task_id>")
class TaskById(MethodView):
    @blp.doc(operationId="getTask", summary="Get a task")
    @blp.response(200, TaskSchema, description="The requested task.")
    @blp.alt_response(404, schema=ErrorSchema, description="The task was not found.")
    def get(self, task_id: int) -> dict[str, Any]:
        """Retrieve a single task by its identifier."""
        return _find_task_or_404(task_id)

    @blp.doc(operationId="updateTask", summary="Update a task")
    @blp.arguments(TaskUpdateSchema)
    @blp.response(200, TaskSchema, description="The updated task.")
    @blp.alt_response(404, schema=ErrorSchema, description="The task was not found.")
    @blp.alt_response(422, schema=ErrorSchema, description="The supplied fields are invalid.")
    def put(self, payload: dict[str, Any], task_id: int) -> dict[str, Any]:
        """Modify the title and/or completion state of an existing task."""
        task = _find_task_or_404(task_id)
        if "title" in payload:
            task["title"] = payload["title"].strip()
        if "finished" in payload:
            task["finished"] = payload["finished"]
        return task

    @blp.doc(operationId="deleteTask", summary="Delete a task")
    @blp.response(200, DeleteResultSchema, description="Deletion succeeded.")
    @blp.alt_response(404, schema=ErrorSchema, description="The task was not found.")
    def delete(self, task_id: int) -> dict[str, str]:
        """Remove a task from storage."""
        task = _find_task_or_404(task_id)
        with _store_lock:
            tasks.remove(task)
        return {"message": "Task deleted"}


api.register_blueprint(blp)

# Note: flask-smorest registers a JSON error handler for HTTPException at
# Api(app) init, so routing-level errors (GET /tasks/abc, PATCH /tasks/1)
# return JSON rather than Werkzeug's HTML. No handler of our own is needed.


@app.route("/")
def index() -> Any:
    """Serve the Alpine.js demo front end.

    Deliberately outside the API Blueprint — it is a page, not an endpoint,
    so it is excluded from the OpenAPI document (see UNDOCUMENTED_ENDPOINTS
    in the tests).
    """
    return app.send_static_file("index.html")


def _dump_openapi(path: str) -> None:
    """Write the generated OpenAPI document to *path*.

    Called only from the CLI — never at import time.
    """
    import json

    with app.app_context():
        spec = api.spec.to_dict()
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(spec, handle, indent=2)
        handle.write("\n")
    print(f"Wrote {path}")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Task API")
    parser.add_argument(
        "--dump-openapi",
        metavar="PATH",
        nargs="?",
        const="openapi.json",
        help="Write the OpenAPI document to PATH (default: openapi.json) and exit.",
    )
    args = parser.parse_args()

    if args.dump_openapi:
        _dump_openapi(args.dump_openapi)
    else:
        app.run(debug=True)
