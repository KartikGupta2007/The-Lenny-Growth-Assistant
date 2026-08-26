"""Shared pytest fixtures.

Tests run against a dedicated ``lenny_growth_assistant_test`` database so a
run never disturbs ingested corpus data. Nothing here contacts a cloud
provider; model and embedding providers are stubbed in the tests that need
them.

Settings are built with ``_env_file=None`` so a developer's local
``backend/.env`` cannot change what the suite asserts. Anything the tests need
is set explicitly below.
"""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest

# Configure the environment before any application module is imported, since
# Settings is cached on first access.
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+psycopg://localhost:5432/lenny_growth_assistant_test",
)
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("LOG_LEVEL", "WARNING")

from fastapi.testclient import TestClient  # noqa: E402

from app.config import Settings  # noqa: E402
from app.main import create_app  # noqa: E402


@pytest.fixture(scope="session")
def settings() -> Settings:
    """Application settings bound to the test database."""
    return Settings(
        _env_file=None,
        app_env="test",
        log_level="WARNING",
        database_url=os.environ["DATABASE_URL"],
        embedding_provider="ollama",
        embedding_model="nomic-embed-text",
    )


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    """A TestClient over a freshly built app instance."""
    app = create_app(settings)
    with TestClient(app) as test_client:
        yield test_client
