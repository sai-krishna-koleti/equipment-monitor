"""SQLAlchemy engine, session factory, and FastAPI database-session dependency."""

from collections.abc import Generator
import sqlite3

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings

settings = get_settings()
_is_sqlite = settings.database_url.startswith("sqlite")
_connect_args = (
    {"check_same_thread": False, "timeout": 30.0}
    if _is_sqlite
    else {}
)

engine = create_engine(
    settings.database_url,
    connect_args=_connect_args,
    pool_pre_ping=True,
)


def _configure_sqlite_connection(
    dbapi_connection: sqlite3.Connection,
    _connection_record: object,
) -> None:
    """Enable relational integrity and lock waiting for SQLite connections."""
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA busy_timeout=30000")
    finally:
        cursor.close()


if _is_sqlite:
    event.listen(engine, "connect", _configure_sqlite_connection)

SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
)


def get_db() -> Generator[Session, None, None]:
    """Yield a database session and always close it after the request."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
