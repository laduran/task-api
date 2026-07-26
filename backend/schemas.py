"""Marshmallow schemas.

These drive both request validation and the generated OpenAPI document, so a
change here is automatically reflected in ``openapi.json``.
"""

from __future__ import annotations

from typing import Any

from marshmallow import Schema, ValidationError, fields, validate, validates_schema


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
