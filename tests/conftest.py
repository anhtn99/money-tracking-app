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
from app.database import Base, engine
from app.main import app


@pytest.fixture(autouse=True)
def _fresh_schema():
    Base.metadata.create_all(engine)
    yield
    Base.metadata.drop_all(engine)


@pytest.fixture
def client():
    return TestClient(app)
