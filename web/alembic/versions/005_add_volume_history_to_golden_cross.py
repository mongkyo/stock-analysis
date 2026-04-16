"""add volume_history to golden_cross_logs

Revision ID: 005
Revises: 004
Create Date: 2026-04-16
"""

from alembic import op
import sqlalchemy as sa

revision = '005'
down_revision = '004'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'golden_cross_logs',
        sa.Column('volume_history', sa.Text(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column('golden_cross_logs', 'volume_history')
