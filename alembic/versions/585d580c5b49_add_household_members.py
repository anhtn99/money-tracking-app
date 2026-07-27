"""add household members

Revision ID: 585d580c5b49
Revises: a2e6c8f1d3b7
Create Date: 2026-07-27 20:19:51.823021

New table + seed data, replacing the hardcoded HOUSEHOLD_SPLIT constant
that used to live in app/services/shared_expenses.py -- seeds the exact
same two rows (Anh 70%, Michelle 30%, same settlement patterns) so
existing behavior is unchanged until someone actually edits the set via
PUT /household-members.
"""
import uuid
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import table, column


# revision identifiers, used by Alembic.
revision = '585d580c5b49'
down_revision = 'a2e6c8f1d3b7'
branch_labels = None
depends_on = None

household_members_table = table(
    "household_members",
    column("id", UUID(as_uuid=True)),
    column("name", sa.String),
    column("percentage", sa.Numeric(5, 4)),
    column("settlement_patterns", sa.JSON),
    column("display_order", sa.Integer),
)


def upgrade() -> None:
    op.create_table(
        "household_members",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("percentage", sa.Numeric(5, 4), nullable=False),
        sa.Column("settlement_patterns", sa.JSON(), nullable=False),
        sa.Column("display_order", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()
        ),
    )

    op.bulk_insert(household_members_table, [
        {
            "id": uuid.uuid4(),
            "name": "Anh",
            "percentage": "0.7000",
            "settlement_patterns": ["online transfer from chk"],
            "display_order": 0,
        },
        {
            "id": uuid.uuid4(),
            "name": "Michelle",
            "percentage": "0.3000",
            "settlement_patterns": ["capital one transfer"],
            "display_order": 1,
        },
    ])


def downgrade() -> None:
    op.drop_table("household_members")
