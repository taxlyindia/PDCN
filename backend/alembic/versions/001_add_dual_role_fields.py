"""Add dual-role fields and finance_cfa_team enum value

Revision ID: 001_add_dual_role_fields
Revises:
Create Date: 2025-01-01 00:00:00
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text

revision = '001_add_dual_role_fields'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    # Step 1: Add the new enum value.
    # Must be done OUTSIDE a transaction in PostgreSQL, so we use AUTOCOMMIT.
    conn = op.get_bind()
    conn.execution_options(isolation_level="AUTOCOMMIT").execute(
        text("ALTER TYPE userrole ADD VALUE IF NOT EXISTS 'finance_cfa_team'")
    )

    # Step 2: Add the two boolean columns (nullable first, then set default after backfill)
    op.add_column('users', sa.Column('is_finance_team', sa.Boolean(), nullable=True))
    op.add_column('users', sa.Column('is_cfa_team', sa.Boolean(), nullable=True))

    # Step 3: Back-fill using the TEXT cast to avoid enum comparison issues
    op.execute(text("""
        UPDATE users SET
            is_finance_team = CASE WHEN role::text IN ('finance_team', 'finance_cfa_team') THEN true ELSE false END,
            is_cfa_team     = CASE WHEN role::text IN ('cfa_team',     'finance_cfa_team') THEN true ELSE false END
    """))

    # Step 4: Now set NOT NULL + default
    op.alter_column('users', 'is_finance_team', nullable=False, server_default='false')
    op.alter_column('users', 'is_cfa_team',     nullable=False, server_default='false')


def downgrade():
    op.drop_column('users', 'is_cfa_team')
    op.drop_column('users', 'is_finance_team')
    # PostgreSQL does not support removing enum values natively
