"""Database engine and per-request session management.

The connection string always comes from the ``DATABASE_URL`` environment
variable so that moving between environments is a config change rather than a
code change. The default points at the local docker-compose database.
"""

from __future__ import annotations

import os

from flask import Flask, current_app, g
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

DEFAULT_DATABASE_URL = "postgresql+psycopg://taskapi:taskapi@127.0.0.1:5432/taskapi"


class Base(DeclarativeBase):
    """Declarative base shared by every model."""


def normalise_driver(url: str) -> str:
    """Force the psycopg (v3) driver in a connection URL.

    Hosted providers hand out URLs that name no driver: Neon and Render use
    ``postgresql://``, which SQLAlchemy maps to **psycopg2** — a package we
    deliberately do not install — and Heroku-style ``postgres://``, which
    SQLAlchemy rejects outright. Rewriting the scheme here means a platform's
    connection string can be pasted in unmodified.

    A URL that already names a driver (``postgresql+psycopg://``) is returned
    untouched, as are non-Postgres URLs.
    """
    if url.startswith("postgresql+"):
        return url
    for prefix in ("postgresql://", "postgres://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix) :]
    return url


def database_url() -> str:
    return normalise_driver(os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL))


def init_app(app: Flask, url: str | None = None) -> None:
    """Attach an engine and session factory to *app*.

    ``create_engine`` does not open a connection, so this is safe to call
    without a reachable database — the spec dump relies on that.
    """
    engine = create_engine(
        normalise_driver(url) if url else database_url(),
        # Postgres connections are dropped by idle timeouts and by restarts of
        # the database container; pre-ping discards dead ones transparently.
        pool_pre_ping=True,
    )
    app.extensions["engine"] = engine
    app.extensions["session_factory"] = sessionmaker(
        bind=engine,
        # Keep attributes loaded after commit so the response can be
        # serialised without issuing another SELECT.
        expire_on_commit=False,
    )
    app.teardown_appcontext(_shutdown_session)


def session() -> Session:
    """Return the session for the current request, opening it on first use."""
    if "db_session" not in g:
        g.db_session = current_app.extensions["session_factory"]()
    return g.db_session


def _shutdown_session(exception: BaseException | None) -> None:
    """Roll back and close at the end of the request.

    Views commit explicitly; this is the safety net for the paths that raise.
    """
    existing = g.pop("db_session", None)
    if existing is None:
        return
    if exception is not None:
        existing.rollback()
    existing.close()
