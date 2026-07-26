"""SQLAlchemy models."""

from __future__ import annotations

from sqlalchemy import Boolean, Integer, Text, false
from sqlalchemy.orm import Mapped, mapped_column

from db import Base


class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    # Text rather than String(n): a length limit is enforced by Postgres but
    # silently ignored by SQLite, and the useful validation (non-blank) already
    # lives in the marshmallow schema.
    title: Mapped[str] = mapped_column(Text, nullable=False)

    finished: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )

    def __repr__(self) -> str:
        return f"<Task id={self.id!r} finished={self.finished!r}>"
