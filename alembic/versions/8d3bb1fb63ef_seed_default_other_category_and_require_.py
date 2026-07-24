"""seed default Other category and require transaction category

Revision ID: 8d3bb1fb63ef
Revises: 2ca9cd3f2e6a
Create Date: 2026-07-24 06:04:23.531071

Data migration, not just schema: seeds the one-and-only "Other" category
(is_default=True) and backfills every existing transaction with a null
category_id to point at it, BEFORE making the column NOT NULL -- ordering
matters here, since altering to NOT NULL first would fail against any
existing null rows.
"""
import uuid

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import table, column


# revision identifiers, used by Alembic.
revision = '8d3bb1fb63ef'
down_revision = '2ca9cd3f2e6a'
branch_labels = None
depends_on = None

OTHER_CATEGORY_ID = uuid.uuid4()

categories_table = table(
    "categories",
    column("id", UUID(as_uuid=True)),
    column("name", sa.String),
    column("color", sa.String),
    column("icon", sa.String),
    column("is_default", sa.Boolean),
)
transactions_table = table(
    "transactions",
    column("category_id", UUID(as_uuid=True)),
)


def upgrade() -> None:
    # server_default here is only to satisfy existing rows during the ALTER
    # TABLE -- dropped right after, since the model's Python-side default
    # (False) is what should govern new rows going forward.
    op.add_column(
        "categories",
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.alter_column("categories", "is_default", server_default=None)

    op.bulk_insert(categories_table, [{
        "id": OTHER_CATEGORY_ID,
        "name": "Other",
        "color": "#9E9E9E",
        "icon": "🤷",
        "is_default": True,
    }])

    op.execute(
        transactions_table.update()
        .where(transactions_table.c.category_id.is_(None))
        .values(category_id=OTHER_CATEGORY_ID)
    )

    op.alter_column("transactions", "category_id", existing_type=UUID(as_uuid=True), nullable=False)


def downgrade() -> None:
    # Don't rely on OTHER_CATEGORY_ID here -- it's regenerated fresh on
    # every separate `alembic` invocation (module-level, evaluated at
    # import time), so a downgrade run as its own command would have a
    # different value than whatever upgrade() actually inserted. Look up
    # the real seeded row's id instead.
    op.alter_column("transactions", "category_id", existing_type=UUID(as_uuid=True), nullable=True)

    bind = op.get_bind()
    other_id = bind.execute(
        sa.select(categories_table.c.id).where(categories_table.c.is_default.is_(True))
    ).scalar()
    if other_id is not None:
        op.execute(
            transactions_table.update()
            .where(transactions_table.c.category_id == other_id)
            .values(category_id=None)
        )

    op.execute(categories_table.delete().where(categories_table.c.is_default.is_(True)))
    op.drop_column("categories", "is_default")
