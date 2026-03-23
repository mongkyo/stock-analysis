"""
[alembic/versions/002] analysis_results에 score 컬럼 추가

Revision ID: 002
Revises: 001
Create Date: 2026-03-23
"""

from alembic import op
import sqlalchemy as sa

revision = "002"
down_revision = "001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "analysis_results",
        sa.Column("score", sa.Float(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("analysis_results", "score")
