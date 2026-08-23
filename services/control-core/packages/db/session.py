"""Database session management — reads settings from config with env-var fallback."""

import asyncio
import logging
import os
from collections.abc import Generator
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

logger = logging.getLogger(__name__)


def _build_engine():
    """Build engine from config settings with env-var fallback."""
    from packages.config import get_settings

    try:
        settings = get_settings()
        db_url = settings.database.url
        db_echo = settings.database.echo
        pool_pre_ping = settings.database.pool_pre_ping
        pool_size = settings.database.pool_size
        max_overflow = settings.database.max_overflow
        pool_recycle = settings.database.pool_recycle
    except Exception as e:
        logger.warning("Failed to load settings for DB engine, using env-var fallback: %s", e)
        # Fallback to raw env vars if config loading fails (e.g. missing YAML)
        db_url = os.getenv("DATABASE_URL", "sqlite:///./data/agent_platform.db")
        db_echo = os.getenv("DB_ECHO", "").lower() in ("1", "true")
        pool_pre_ping = True
        pool_size = int(os.getenv("DB_POOL_SIZE", "5"))
        max_overflow = int(os.getenv("DB_MAX_OVERFLOW", "10"))
        pool_recycle = int(os.getenv("DB_POOL_RECYCLE", "3600"))

    # Ensure data directory exists for SQLite
    if db_url.startswith("sqlite"):
        # Create the parent of the configured database, not a cwd-relative
        # ``./data`` directory.  Installed sidecars run from Program Files and
        # keep their writable SQLite database under %LOCALAPPDATA%.
        sqlite_path = db_url.removeprefix("sqlite:///")
        if sqlite_path != ":memory:":
            Path(sqlite_path).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)

    is_sqlite = db_url.startswith("sqlite")

    if is_sqlite:
        return create_engine(
            db_url,
            echo=db_echo,
            connect_args={"check_same_thread": False, "timeout": 30},
            pool_pre_ping=pool_pre_ping,
        )

    return create_engine(
        db_url,
        echo=db_echo,
        pool_pre_ping=pool_pre_ping,
        pool_size=pool_size,
        max_overflow=max_overflow,
        pool_recycle=pool_recycle,
    )


engine = _build_engine()

if engine.dialect.name == "sqlite":
    from sqlalchemy import event

    @event.listens_for(engine, "connect")
    def _set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""

    pass


def run_in_thread(func, *args, bind_engine=None, **kwargs):
    """Run a sync DB function in a background thread with its own session.

    Creates a fresh Session, calls ``func(db, *args, **kwargs)``, commits on
    success, rolls back on error, and always closes the session.
    Returns whatever *func* returns.

    Pass ``bind_engine=db.bind`` in route handlers to use the same engine as
    the request's overridden DB (important for integration tests).
    """
    if bind_engine is not None:
        factory = sessionmaker(bind=bind_engine, autocommit=False, autoflush=False, expire_on_commit=False)
        db = factory()
    else:
        db = SessionLocal()
        db.expire_on_commit = False  # allow detached attribute access after commit+close
    try:
        result = func(db, *args, **kwargs)
        db.commit()
        return result
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency that yields a DB session with auto commit/rollback."""
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


async def run_async(func, *args, bind_engine=None, _db=None, **kwargs):
    """Async wrapper that runs a sync DB function in a thread with its own session.

    Each call creates a fresh, thread-local Session — safe for concurrent use.
    Prefer this over ``asyncio.to_thread(repo, db, ...)`` which leaks the
    caller's session into another thread.

    Pass ``_db=session`` to reuse an existing session (test backward-compat only).
    """
    if _db is not None:
        return await asyncio.to_thread(func, _db, *args, **kwargs)
    return await asyncio.to_thread(run_in_thread, func, *args, bind_engine=bind_engine, **kwargs)
