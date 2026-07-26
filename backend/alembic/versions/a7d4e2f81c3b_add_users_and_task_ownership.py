"""add users table and task ownership

Revision ID: a7d4e2f81c3b
Revises: f3a1c9e7b210
Create Date: 2026-07-26 20:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a7d4e2f81c3b'
down_revision: Union[str, Sequence[str], None] = 'f3a1c9e7b210'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('users',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('google_sub', sa.String(length=255), nullable=False),
    sa.Column('email', sa.String(length=320), nullable=False),
    sa.Column('name', sa.Text(), nullable=False),
    sa.Column('picture_url', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('google_sub')
    )
    # Nullable on purpose: existing rows have no owner and simply become
    # invisible once every query filters by owner_id — not deleted, just
    # unclaimed. A NOT NULL column here would require a backfill decision
    # this migration has no way to make on its own.
    op.add_column('tasks', sa.Column('owner_id', sa.Integer(), nullable=True))
    op.create_foreign_key(
        'fk_tasks_owner_id_users', 'tasks', 'users', ['owner_id'], ['id']
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint('fk_tasks_owner_id_users', 'tasks', type_='foreignkey')
    op.drop_column('tasks', 'owner_id')
    op.drop_table('users')
