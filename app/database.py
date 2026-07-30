"""
SQLAlchemy engine, session factory, and declarative Base -- everything
that depends on how/where the data is actually stored. Models import Base
from here; routers will import get_db as a FastAPI dependency (added in
Phase 2, once we start building real endpoints).
"""
from sqlalchemy import create_engine, event
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

    # Unlike Postgres, SQLite doesn't enforce FOREIGN KEY constraints
    # unless told to per-connection -- without this, any test relying on
    # FK enforcement (e.g. a bad reference correctly raising
    # IntegrityError) would silently pass against SQLite while only
    # actually being enforced against the real Postgres database, a
    # false-negative test gap. Not tied to one specific route's behavior
    # -- worth remembering whenever a test passes suspiciously easily.
    @event.listens_for(engine, "connect")
    def _enable_sqlite_foreign_keys(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()
else:
    # pool_pre_ping issues a cheap SELECT 1 before handing out a pooled
    # connection, transparently discarding+replacing it if the check
    # fails -- matters once the app is a long-running process talking to
    # a database over a real network hop (RDS/Aurora) instead of the same
    # Docker network. Without it, a connection dropped silently (an RDS
    # failover, an idle timeout, an Aurora Serverless v2 scaling event)
    # surfaces as a confusing mid-request error instead of the pool just
    # quietly getting a fresh connection.
    engine = create_engine(settings.database_url, pool_pre_ping=True)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    """FastAPI dependency -- yields a session, always closes it after."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
