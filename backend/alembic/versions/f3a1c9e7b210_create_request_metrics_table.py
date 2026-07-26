"""create request_metrics table

Revision ID: f3a1c9e7b210
Revises: b9cd293e0217
Create Date: 2026-07-26 06:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f3a1c9e7b210'
down_revision: Union[str, Sequence[str], None] = 'b9cd293e0217'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('request_metrics',
    sa.Column('minute', sa.DateTime(timezone=True), nullable=False),
    sa.Column('status_class', sa.String(length=3), nullable=False),
    sa.Column('count', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('total_duration_ms', sa.BigInteger(), server_default=sa.text('0'), nullable=False),
    sa.Column('max_duration_ms', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.PrimaryKeyConstraint('minute', 'status_class')
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('request_metrics')
