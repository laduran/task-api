"""drop request_metrics table

Revision ID: d4f7a2c9e831
Revises: c1e5b8a4d9f2
Create Date: 2026-07-28 12:00:00.000000

The home-grown request-metrics dashboard is retired in favor of the
OpenTelemetry -> Grafana Cloud pipeline added in a previous change. Nothing
else reads or writes this table.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'd4f7a2c9e831'
down_revision: Union[str, Sequence[str], None] = 'c1e5b8a4d9f2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.drop_table('request_metrics')


def downgrade() -> None:
    """Downgrade schema."""
    op.create_table('request_metrics',
    sa.Column('minute', sa.DateTime(timezone=True), nullable=False),
    sa.Column('status_class', sa.String(length=3), nullable=False),
    sa.Column('count', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('total_duration_ms', sa.BigInteger(), server_default=sa.text('0'), nullable=False),
    sa.Column('max_duration_ms', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.PrimaryKeyConstraint('minute', 'status_class')
    )
