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


@pytest.fixture(autouse=True)
def _fresh_schema():
    """create_all() builds the schema straight from the models, bypassing
    Alembic entirely -- so the "Other" category seeded by migration
    8d3bb1fb63ef never exists here unless we seed it ourselves too. Every
    transaction requires a category (NOT NULL), so this has to exist
    before any test can create one."""
    Base.metadata.create_all(engine)
    db = SessionLocal()
    db.add(Category(name="Other", color="#9E9E9E", icon="🤷", is_default=True))
    db.commit()
    db.close()
    yield
    Base.metadata.drop_all(engine)


@pytest.fixture
def client():
    return TestClient(app)
