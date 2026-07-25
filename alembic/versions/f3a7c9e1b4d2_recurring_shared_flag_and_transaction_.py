"""recurring is_shared flag and transaction display_name

Revision ID: f3a7c9e1b4d2
Revises: 8d3bb1fb63ef
Create Date: 2026-07-24 07:00:00.000000

Two independent additive changes for Phase 5 (Recurring tab):
  - recurring_rules.is_shared -- plain boolean, no data migration needed.
  - transactions.display_name -- data migration: backfill from the
    existing `name` column BEFORE making it NOT NULL, same ordering
    reasoning as 8d3bb1fb63ef's category_id backfill.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.sql import table, column


# revision identifiers, used by Alembic.
revision = 'f3a7c9e1b4d2'
down_revision = '8d3bb1fb63ef'
branch_labels = None
depends_on = None

transactions_table = table(
    "transactions",
    column("name", sa.String),
    column("display_name", sa.String),
)


def upgrade() -> None:
    op.add_column(
        "recurring_rules",
        sa.Column("is_shared", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.alter_column("recurring_rules", "is_shared", server_default=None)

    op.add_column("transactions", sa.Column("display_name", sa.String(), nullable=True))
    op.execute(transactions_table.update().values(display_name=transactions_table.c.name))
    op.alter_column("transactions", "display_name", existing_type=sa.String(), nullable=False)


def downgrade() -> None:
    op.drop_column("transactions", "display_name")
    op.drop_column("recurring_rules", "is_shared")
