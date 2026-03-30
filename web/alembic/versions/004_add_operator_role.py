"""add operator role to userrole enum

Revision ID: 004
Revises: 003
Create Date: 2026-03-30
"""
from alembic import op

revision = '004'
down_revision = '003'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # PostgreSQL Enum에 새 값 추가 (트랜잭션 밖에서 실행해야 함)
    op.execute("ALTER TYPE userrole ADD VALUE IF NOT EXISTS 'operator'")


def downgrade() -> None:
    # PostgreSQL은 Enum 값 제거를 지원하지 않으므로 downgrade 생략
    pass
