"""Database engines and session management.

The async engine serves request handlers; the sync engine is for batch work
(Alembic, ingestion), which has nothing to overlap. psycopg 3 provides both
interfaces, so one normalised DSN serves both.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Iterator
from contextlib import contextmanager
from functools import lru_cache

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings
from app.errors import DatabaseUnavailableError
from app.logging_config import get_logger

logger = get_logger(__name__)


@lru_cache(maxsize=1)
def get_engine() -> AsyncEngine:
    return create_async_engine(
        get_settings().sqlalchemy_url,
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=5,
        echo=False,
    )


@lru_cache(maxsize=1)
def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(bind=get_engine(), expire_on_commit=False, autoflush=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency yielding a transactional session.

    Commits on success and rolls back on failure, so handlers never manage
    transactions and several repository calls form one unit of work. Driver
    errors become DatabaseUnavailableError so the API leaks no driver detail.
    """
    factory = get_sessionmaker()
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except SQLAlchemyError as exc:
            await session.rollback()
            logger.error("database_error", error=str(exc), exc_info=True)
            raise DatabaseUnavailableError() from exc
        except Exception:
            await session.rollback()
            raise


async def check_database() -> tuple[bool, str | None]:
    """Probe connectivity and pgvector. Never raises.

    Bounded by DATABASE_PROBE_TIMEOUT_SECONDS: a host that accepts the TCP
    connection but never answers would otherwise hang the health endpoint.
    """

    async def probe() -> tuple[bool, str | None]:
        async with get_engine().connect() as conn:
            await conn.execute(text("SELECT 1"))
            installed = await conn.execute(
                text("SELECT 1 FROM pg_extension WHERE extname = 'vector'")
            )
            if installed.first() is None:
                return False, "pgvector extension is not installed"
        return True, None

    timeout = get_settings().database_probe_timeout_seconds
    try:
        return await asyncio.wait_for(probe(), timeout=timeout)
    except TimeoutError:
        logger.error("database_error", reason="probe_timeout", timeout=timeout)
        return False, "database did not respond in time"
    except Exception as exc:
        logger.error("database_error", error=str(exc), exc_info=True)
        return False, "cannot connect to database"


# ---------------------------------------------------------------------------
# Synchronous access, for batch ingestion.
# ---------------------------------------------------------------------------


@lru_cache(maxsize=1)
def get_sync_engine() -> Engine:
    return create_engine(get_settings().sqlalchemy_url, pool_pre_ping=True, echo=False)


@contextmanager
def sync_session() -> Iterator[Session]:
    """A blocking, transactional session for batch work."""
    factory = sessionmaker(bind=get_sync_engine(), expire_on_commit=False)
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
