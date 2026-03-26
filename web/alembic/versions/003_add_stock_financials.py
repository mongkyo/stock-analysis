"""add stock_financials table

Revision ID: 003
Revises: 002
Create Date: 2026-03-26
"""
from alembic import op
import sqlalchemy as sa

revision = '003'
down_revision = '002'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'stock_financials',
        sa.Column('id',           sa.Integer(),     nullable=False),
        sa.Column('code',         sa.String(6),     nullable=False),
        sa.Column('name',         sa.String(50),    nullable=False),
        sa.Column('roe',          sa.Float(),       nullable=True),
        sa.Column('op_margin',    sa.Float(),       nullable=True),
        sa.Column('fetched_date', sa.String(8),     nullable=False),
        sa.Column('created_at',   sa.DateTime(),    nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('code', 'fetched_date',
                            name='uq_stock_financial_code_date'),
    )
    op.create_index('ix_stock_financials_code',         'stock_financials', ['code'])
    op.create_index('ix_stock_financials_fetched_date', 'stock_financials', ['fetched_date'])


def downgrade() -> None:
    op.drop_index('ix_stock_financials_fetched_date', table_name='stock_financials')
    op.drop_index('ix_stock_financials_code',         table_name='stock_financials')
    op.drop_table('stock_financials')
