"""
SQLAlchemy engine, session factory, and declarative Base -- everything
that depends on how/where the data is actually stored. Models import Base
from here; routers will import get_db as a FastAPI dependency (added in
Phase 2, once we start building real endpoints).
"""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

from app.core.config import settings

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
