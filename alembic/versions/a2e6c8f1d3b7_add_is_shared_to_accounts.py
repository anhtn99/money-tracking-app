"""add is_shared to accounts

Revision ID: a2e6c8f1d3b7
Revises: f3a7c9e1b4d2
Create Date: 2026-07-24 22:00:00.000000

Plain additive column, no data migration needed -- Phase 6 (Shared
Expenses).
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a2e6c8f1d3b7'
down_revision = 'f3a7c9e1b4d2'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "accounts",
        sa.Column("is_shared", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.alter_column("accounts", "is_shared", server_default=None)


def downgrade() -> None:
    op.drop_column("accounts", "is_shared")
