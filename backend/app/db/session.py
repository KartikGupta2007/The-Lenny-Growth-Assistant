"""Database engine, session factory and connectivity probe.

The async engine serves request handlers; the sync engine is used by the
ingestion CLI (``python -m app.ingestion.sync``), which is a batch process and
does not benefit from async I/O.
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
from app.constants import (
    ASYNC_DRIVER_PREFIX,
    BARE_POSTGRES_PREFIX,
    DB_MAX_OVERFLOW,
    DB_POOL_SIZE,
    SQL_PGVECTOR_INSTALLED,
    SQL_PING,
)
from app.errors import DatabaseUnavailableError
from app.logging_config import get_logger

logger = get_logger(__name__)


def _async_url(url: str) -> str:
    """Normalise a DSN onto the async psycopg driver."""
    if url.startswith(ASYNC_DRIVER_PREFIX):
        return url
    if url.startswith(BARE_POSTGRES_PREFIX):
        return url.replace(BARE_POSTGRES_PREFIX, ASYNC_DRIVER_PREFIX, 1)
    return url


@lru_cache(maxsize=1)
def get_engine() -> AsyncEngine:
    """Return the process-wide async engine."""
    settings = get_settings()
    return create_async_engine(
        _async_url(settings.database_url),
        pool_pre_ping=True,
        pool_size=DB_POOL_SIZE,
        max_overflow=DB_MAX_OVERFLOW,
        echo=False,
    )


@lru_cache(maxsize=1)
def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    """Return the process-wide async session factory."""
    return async_sessionmaker(
        bind=get_engine(),
        expire_on_commit=False,
        autoflush=False,
    )


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency yielding a transactional session.

    Commits on success and rolls back on failure, so route handlers never have
    to manage transactions themselves. Driver-level errors are translated into
    :class:`DatabaseUnavailableError` so the API never leaks driver detail.
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


async def _probe() -> tuple[bool, str | None]:
    """Run the connectivity and extension checks."""
    engine = get_engine()
    async with engine.connect() as conn:
        await conn.execute(text("SELECT 1"))
        result = await conn.execute(
            text("SELECT 1 FROM pg_extension WHERE extname = \'vector\'")
        )
        if result.first() is None:
            return False, "pgvector extension is not installed"
    return True, None


async def check_database() -> tuple[bool, str | None]:
    """Probe database connectivity and pgvector availability.

    Bounded by ``DATABASE_PROBE_TIMEOUT_SECONDS``: a host that accepts the TCP
    connection but never answers would otherwise hang the health endpoint for
    the driver\'s full connect timeout, which is exactly when a probe most
    needs to return.

    Returns:
        ``(healthy, detail)``. ``detail`` is ``None`` when healthy, otherwise a
        short diagnostic string for the health payload. Never raises -- an
        unreachable database is a reportable state, not an error.
    """
    timeout = get_settings().database_probe_timeout_seconds
    try:
        return await asyncio.wait_for(_probe(), timeout=timeout)
    except TimeoutError:
        logger.error("database_error", reason="probe_timeout", timeout=timeout)
        return False, "database did not respond in time"
    except SQLAlchemyError as exc:
        logger.error("database_error", error=str(exc))
        return False, "cannot connect to database"
    except Exception as exc:  # driver/DNS failures that escape SQLAlchemy
        logger.error("database_error", error=str(exc), exc_info=True)
        return False, "cannot connect to database"


# ---------------------------------------------------------------------------
# Synchronous access, for the ingestion CLI only.
# ---------------------------------------------------------------------------


@lru_cache(maxsize=1)
def get_sync_engine() -> Engine:
    """Return a blocking engine for batch ingestion."""
    settings = get_settings()
    return create_engine(settings.sync_database_url, pool_pre_ping=True, echo=False)


@contextmanager
def sync_session() -> Iterator[Session]:
    """Yield a blocking, transactional session for batch work."""
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
