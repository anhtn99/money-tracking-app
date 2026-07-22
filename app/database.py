"""
SQLAlchemy engine, session factory, and declarative Base -- everything
that depends on how/where the data is actually stored. Models import Base
from here; routers will import get_db as a FastAPI dependency (added in
Phase 2, once we start building real endpoints).
"""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy.pool import StaticPool

from app.core.config import settings

# SQLite needs check_same_thread=False (FastAPI dispatches sync endpoints
# onto a worker thread) plus StaticPool for the in-memory case (a fresh
# :memory: DB per connection would otherwise look empty to every request
# but the one that created it) -- only relevant for tests, which point
# DATABASE_URL at sqlite:// instead of the real Postgres instance.
if settings.database_url.startswith("sqlite"):
    engine = create_engine(
        settings.database_url,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
else:
    engine = create_engine(settings.database_url)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    """FastAPI dependency -- yields a session, always closes it after."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
