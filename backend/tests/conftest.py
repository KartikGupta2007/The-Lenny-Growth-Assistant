"""Shared pytest fixtures.

Database tests run against real PostgreSQL with pgvector: the schema's value
is in its constraints, cascades and vector column, none of which exist in a
stand-in. They fail rather than skip when the database is unreachable, because
a skipped constraint test looks exactly like a passing one.

Set TEST_DATABASE_URL to use a specific database (a Neon test branch, say);
otherwise a local lenny_growth_assistant_test. DATABASE_URL is overwritten
rather than defaulted, so the suite cannot reach the application database in
backend/.env -- these fixtures create and drop schema.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Iterator

import pytest
import pytest_asyncio

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL") or (
    "postgresql+psycopg://localhost:5432/lenny_growth_assistant_test"
)
os.environ["DATABASE_URL"] = TEST_DATABASE_URL
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("LOG_LEVEL", "WARNING")

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import text  # noqa: E402
from sqlalchemy.ext.asyncio import (  # noqa: E402
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool  # noqa: E402

from app.config import Settings  # noqa: E402
from app.constants import BACKEND_DIR  # noqa: E402
from app.main import create_app  # noqa: E402

_UNREACHABLE = f"""Cannot reach the test database at {TEST_DATABASE_URL.split('@')[-1]}.
Create it with:
  createdb lenny_growth_assistant_test
  psql -d lenny_growth_assistant_test -c "CREATE EXTENSION IF NOT EXISTS vector;"
or set TEST_DATABASE_URL to a reachable database.
Original error: {{error}}"""


@pytest.fixture(scope="session")
def settings() -> Settings:
    return Settings(
        _env_file=None,
        app_env="test",
        log_level="WARNING",
        database_url=TEST_DATABASE_URL,
    )


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    app = create_app(settings)
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture(scope="session")
def migrated_database() -> str:
    """Bring the test database to the current schema with Alembic.

    downgrade base then upgrade head: every run starts from a known-empty
    schema, and the downgrade path gets exercised on every run. Alembic, not
    create_all, so the tables tested are the tables a deployment gets.
    """
    from alembic import command
    from alembic.config import Config

    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_DIR / "alembic"))

    try:
        command.downgrade(config, "base")
        command.upgrade(config, "head")
    except Exception as error:  # pragma: no cover - environment failure path
        pytest.fail(_UNREACHABLE.format(error=error), pytrace=False)

    return TEST_DATABASE_URL


@pytest_asyncio.fixture
async def db_session(migrated_database: str) -> AsyncIterator[AsyncSession]:
    """A session whose work is rolled back when the test ends.

    Bound to an open connection inside an outer transaction, with
    join_transaction_mode="create_savepoint" so a commit() in code under test
    releases a savepoint instead of committing for real. Tests are isolated
    without re-creating the schema between them.
    """
    engine = create_async_engine(migrated_database, poolclass=NullPool)
    try:
        async with engine.connect() as connection:
            transaction = await connection.begin()
            factory = async_sessionmaker(
                bind=connection,
                expire_on_commit=False,
                join_transaction_mode="create_savepoint",
            )
            async with factory() as session:
                yield session
            await transaction.rollback()
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def pgvector_version(migrated_database: str) -> AsyncIterator[str | None]:
    engine = create_async_engine(migrated_database, poolclass=NullPool)
    try:
        async with engine.connect() as connection:
            result = await connection.execute(
                text("SELECT extversion FROM pg_extension WHERE extname = 'vector'")
            )
            yield result.scalar_one_or_none()
    finally:
        await engine.dispose()
