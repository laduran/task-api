"""SQLAlchemy models."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, Integer, String, Text, false
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


class RequestMetric(Base):
    """One row per (minute, status class), incremented on every request.

    Aggregated at write time rather than storing one row per request: a toy
    app doesn't need per-request detail, and this keeps the table tiny
    (at most 3 rows/minute — 2xx/4xx/5xx) regardless of traffic volume.
    """

    __tablename__ = "request_metrics"

    minute: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    status_class: Mapped[str] = mapped_column(String(3), primary_key=True)

    count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    total_duration_ms: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default="0")
    max_duration_ms: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")

    def __repr__(self) -> str:
        return f"<RequestMetric minute={self.minute!r} status_class={self.status_class!r} count={self.count!r}>"
