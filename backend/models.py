"""SQLAlchemy models."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, String, Text, false
from sqlalchemy.orm import Mapped, mapped_column

from db import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    # Google's stable per-account identifier ("sub" in the ID token). Keyed on
    # this rather than email: an email can be changed or reassigned by the
    # user, sub cannot.
    google_sub: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)

    email: Mapped[str] = mapped_column(String(320), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    picture_url: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    def __repr__(self) -> str:
        return f"<User id={self.id!r} email={self.email!r}>"


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

    # Nullable: rows created before auth existed have no owner. They're not
    # deleted — just invisible to everyone, since every query now filters by
    # owner_id — and nullable means the migration adding this column is a
    # plain ADD COLUMN, not a backfill-or-fail.
    owner_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=True
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
