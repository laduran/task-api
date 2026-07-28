"""add scoped least-privilege app role

Revision ID: c1e5b8a4d9f2
Revises: a7d4e2f81c3b
Create Date: 2026-07-28 10:00:00.000000

The app has always connected as the database's owner role (``neondb_owner``
on Neon), which can CREATEROLE, CREATEDB, and bypasses row-level security —
far more than a CRUD API needs. This creates ``taskapi_app``, scoped to just
DML on this app's own tables, so a SQL-injection bug or a leaked
``DATABASE_URL`` can't be used to touch other databases or escalate.

The role is created NOLOGIN here — same treatment as ``SECRET_KEY``, its
password is never committed. Set one out-of-band (Neon console or
``ALTER ROLE taskapi_app WITH LOGIN PASSWORD '...'``), then point Render's
``DATABASE_URL`` at it. Migrations keep running as the owner role, which is
why ``alembic_version`` is deliberately not granted here.
"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'c1e5b8a4d9f2'
down_revision: Union[str, Sequence[str], None] = 'a7d4e2f81c3b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_APP_TABLES = ("tasks", "users", "request_metrics")


def upgrade() -> None:
    """Upgrade schema."""
    op.execute(
        "DO $$ BEGIN "
        "IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'taskapi_app') THEN "
        "CREATE ROLE taskapi_app NOLOGIN; "
        "END IF; "
        "END $$;"
    )
    # GRANT ... ON DATABASE needs a literal name, not an expression, hence the
    # dynamic EXECUTE — this migration otherwise has no way to know the
    # database name across environments (taskapi locally, neondb on Neon).
    op.execute(
        "DO $$ BEGIN "
        "EXECUTE format('GRANT CONNECT ON DATABASE %I TO taskapi_app', current_database()); "
        "END $$;"
    )
    op.execute("GRANT USAGE ON SCHEMA public TO taskapi_app;")
    op.execute(
        f"GRANT SELECT, INSERT, UPDATE, DELETE ON {', '.join(_APP_TABLES)} TO taskapi_app;"
    )
    op.execute("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO taskapi_app;")
    # Covers tables added by future migrations without a follow-up grant,
    # as long as they keep being created by the owner role (the default).
    op.execute(
        "ALTER DEFAULT PRIVILEGES IN SCHEMA public "
        "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO taskapi_app;"
    )
    op.execute(
        "ALTER DEFAULT PRIVILEGES IN SCHEMA public "
        "GRANT USAGE, SELECT ON SEQUENCES TO taskapi_app;"
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute(
        "ALTER DEFAULT PRIVILEGES IN SCHEMA public "
        "REVOKE USAGE, SELECT ON SEQUENCES FROM taskapi_app;"
    )
    op.execute(
        "ALTER DEFAULT PRIVILEGES IN SCHEMA public "
        "REVOKE SELECT, INSERT, UPDATE, DELETE ON TABLES FROM taskapi_app;"
    )
    op.execute("REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM taskapi_app;")
    op.execute(
        f"REVOKE ALL ON {', '.join(_APP_TABLES)} FROM taskapi_app;"
    )
    op.execute("REVOKE USAGE ON SCHEMA public FROM taskapi_app;")
    op.execute(
        "DO $$ BEGIN "
        "EXECUTE format('REVOKE CONNECT ON DATABASE %I FROM taskapi_app', current_database()); "
        "END $$;"
    )
    # Only safe to run once DATABASE_URL has been reverted to the owner role
    # (or another role) — if taskapi_app is still the live connection role,
    # this drops it out from under production and every new connection fails.
    op.execute("DROP ROLE IF EXISTS taskapi_app;")
