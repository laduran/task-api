"""Alembic environment.

The connection string comes from ``DATABASE_URL`` (via ``db.database_url``)
rather than alembic.ini, so migrations run against whichever environment they
are pointed at without editing a file. The test suite overrides it by setting
``sqlalchemy.url`` on the config object before calling ``command.upgrade``.
"""

from __future__ import annotations

import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import engine_from_config, pool

# Make the backend modules importable however alembic was invoked.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import db  # noqa: E402
import models  # noqa: E402,F401  (imported so its tables register on Base.metadata)

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Autogenerate diffs the live database against this metadata.
target_metadata = db.Base.metadata


def _url() -> str:
    """Prefer an explicitly configured URL, otherwise the environment."""
    return config.get_main_option("sqlalchemy.url") or db.database_url()


def run_migrations_offline() -> None:
    """Emit SQL instead of executing it (``alembic upgrade head --sql``)."""
    context.configure(
        url=_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations against a live connection."""
    section = config.get_section(config.config_ini_section, {})
    section["sqlalchemy.url"] = _url()

    connectable = engine_from_config(section, prefix="sqlalchemy.", poolclass=pool.NullPool)

    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
