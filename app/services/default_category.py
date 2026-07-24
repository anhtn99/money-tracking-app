"""
Looks up the single seeded "Other" category (Category.is_default=True) --
shared by transaction creation/sync (falls back to this when no category
is given) and category deletion (reassignment target). See the migration
that seeds this row (alembic/versions/8d3bb1fb63ef_*.py) for why exactly
one row is guaranteed to have is_default=True.
"""
from sqlalchemy.orm import Session

from app.models.category import Category


def get_default_category(db: Session) -> Category:
    return db.query(Category).filter(Category.is_default.is_(True)).one()
