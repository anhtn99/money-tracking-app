"""
TestClient + in-memory SQLite, same pattern used for the Accounts tab in
Phase 2. Postgres-only features aren't used anywhere in the models (see
the sqlite fallback wired into app/database.py), so the real schema runs
unmodified against SQLite for tests.
"""
import os

os.environ["DATABASE_URL"] = "sqlite://"  # must be set before app.database is ever imported

import pytest
from fastapi.testclient import TestClient

import app.models  # noqa: F401 -- registers every table on Base.metadata
from app.database import Base, SessionLocal, engine
from app.main import app
from app.models.category import Category
from app.models.household_member import HouseholdMember


@pytest.fixture(autouse=True)
def _fresh_schema():
    """create_all() builds the schema straight from the models, bypassing
    Alembic entirely -- so seed data from migrations (the "Other" category
    from 8d3bb1fb63ef, the two default household members from
    585d580c5b49) never exists here unless we seed it ourselves too. Every
    transaction requires a category (NOT NULL), and Shared Expenses splits
    need at least one household member, so both have to exist before most
    tests can run."""
    Base.metadata.create_all(engine)
    db = SessionLocal()
    db.add(Category(name="Other", color="#9E9E9E", icon="🤷", is_default=True))
    db.add_all([
        HouseholdMember(
            name="Anh", percentage="0.7000",
            settlement_patterns=["online transfer from chk"], display_order=0,
        ),
        HouseholdMember(
            name="Michelle", percentage="0.3000",
            settlement_patterns=["capital one transfer"], display_order=1,
        ),
    ])
    db.commit()
    db.close()
    yield
    Base.metadata.drop_all(engine)


@pytest.fixture
def client():
    return TestClient(app)
