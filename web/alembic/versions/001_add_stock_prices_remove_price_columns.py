"""
[alembic/versions/001] stock_prices 테이블 추가, analysis_results 가격 컬럼 제거

Revision ID: 001
Revises:
Create Date: 2026-03-23
"""

from alembic import op
import sqlalchemy as sa

revision = "001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. stock_prices 테이블 생성
    op.create_table(
        "stock_prices",
        sa.Column("id",          sa.Integer(),    primary_key=True),
        sa.Column("code",        sa.String(6),    nullable=False),
        sa.Column("name",        sa.String(50),   nullable=False),
        sa.Column("date",        sa.String(8),    nullable=False),
        sa.Column("close_price", sa.Integer(),    nullable=False),
        sa.Column("created_at",  sa.DateTime(),   nullable=True),
        sa.UniqueConstraint("code", "date", name="uq_stock_price_code_date"),
    )
    op.create_index("ix_stock_prices_code", "stock_prices", ["code"])
    op.create_index("ix_stock_prices_date", "stock_prices", ["date"])

    # 2. analysis_results 에서 가격 컬럼 제거
    op.drop_column("analysis_results", "start_price")
    op.drop_column("analysis_results", "end_price")


def downgrade() -> None:
    # 가격 컬럼 복원 (기본값 0)
    op.add_column("analysis_results",
                  sa.Column("start_price", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("analysis_results",
                  sa.Column("end_price",   sa.Integer(), nullable=False, server_default="0"))

    # stock_prices 테이블 삭제
    op.drop_index("ix_stock_prices_date", "stock_prices")
    op.drop_index("ix_stock_prices_code", "stock_prices")
    op.drop_table("stock_prices")
