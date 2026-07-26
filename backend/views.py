"""HTTP routes for the Task API.

Every operation lives on this Blueprint — flask-smorest only documents routes
registered on a Blueprint, so anything added with a bare ``@app.route`` would
be invisible to the generated spec (a test guards against exactly that).
"""

from __future__ import annotations

from flask.views import MethodView
from flask_smorest import Api, Blueprint, abort
from sqlalchemy import select

import auth
import db
from models import Task
from schemas import DeleteResultSchema, TaskCreateSchema, TaskSchema, TaskUpdateSchema

blp = Blueprint("tasks", __name__, description="Create, read, update and delete tasks.")

# Reuse flask-smorest's own error schema (the shape its error handler emits)
# rather than declaring our own, which would register a duplicate component.
ErrorSchema = Api.ERROR_SCHEMA


def _owner_id() -> int:
    """The signed-in user's id.

    Safe to assume non-None: auth's before_request hook already rejected the
    request with 401 before routing ever reached this Blueprint.
    """
    user = auth.current_user()
    assert user is not None
    return user.id


def _get_task_or_404(task_id: int) -> Task:
    """Fetch a task, scoped to the signed-in user.

    A task that exists but belongs to someone else returns 404, the same as
    one that doesn't exist at all — a 403 here would confirm to an attacker
    that the id belongs to *someone*, just not them.
    """
    task = db.session().scalar(
        select(Task).where(Task.id == task_id, Task.owner_id == _owner_id())
    )
    if task is None:
        abort(404, message="Task not found")
    return task


@blp.route("/tasks")
class TaskCollection(MethodView):
    @blp.doc(operationId="listTasks", summary="List tasks")
    @blp.response(200, TaskSchema(many=True), description="Every stored task.")
    def get(self) -> list[Task]:
        """Return the signed-in user's tasks, oldest first.

        The ordering is explicit on purpose: Postgres makes no guarantee about
        row order without ORDER BY, and an UPDATE can relocate a row.
        """
        return list(
            db.session().scalars(
                select(Task).where(Task.owner_id == _owner_id()).order_by(Task.id)
            )
        )

    @blp.doc(operationId="createTask", summary="Create a task")
    @blp.arguments(TaskCreateSchema)
    @blp.response(201, TaskSchema, description="The newly created task.")
    @blp.alt_response(422, schema=ErrorSchema, description="The title is missing or blank.")
    def post(self, payload: dict[str, object]) -> Task:
        """Create a new task, owned by the signed-in user."""
        session = db.session()
        task = Task(title=str(payload["title"]).strip(), owner_id=_owner_id())
        session.add(task)
        session.commit()
        return task


@blp.route("/tasks/<int:task_id>")
class TaskById(MethodView):
    @blp.doc(operationId="getTask", summary="Get a task")
    @blp.response(200, TaskSchema, description="The requested task.")
    @blp.alt_response(404, schema=ErrorSchema, description="The task was not found.")
    def get(self, task_id: int) -> Task:
        """Retrieve a single task by its identifier."""
        return _get_task_or_404(task_id)

    @blp.doc(operationId="updateTask", summary="Update a task")
    @blp.arguments(TaskUpdateSchema)
    @blp.response(200, TaskSchema, description="The updated task.")
    @blp.alt_response(404, schema=ErrorSchema, description="The task was not found.")
    @blp.alt_response(422, schema=ErrorSchema, description="The supplied fields are invalid.")
    def put(self, payload: dict[str, object], task_id: int) -> Task:
        """Modify the title and/or completion state of an existing task."""
        task = _get_task_or_404(task_id)
        if "title" in payload:
            task.title = str(payload["title"]).strip()
        if "finished" in payload:
            task.finished = bool(payload["finished"])
        db.session().commit()
        return task

    @blp.doc(operationId="deleteTask", summary="Delete a task")
    @blp.response(200, DeleteResultSchema, description="Deletion succeeded.")
    @blp.alt_response(404, schema=ErrorSchema, description="The task was not found.")
    def delete(self, task_id: int) -> dict[str, str]:
        """Remove a task from storage."""
        task = _get_task_or_404(task_id)
        session = db.session()
        session.delete(task)
        session.commit()
        return {"message": "Task deleted"}
