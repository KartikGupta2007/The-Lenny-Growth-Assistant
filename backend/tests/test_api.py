"""API behaviour tests.

Phase 1 covers the health endpoint, the structured error contract and the
degraded-dependency path. Session, message and artifact endpoints are covered
as those phases land.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.errors import AppError, DatabaseUnavailableError
from app.main import create_app


class TestHealth:
    """GET /health"""

    def test_reports_ok_when_database_reachable(self, client: TestClient) -> None:
        response = client.get("/health")

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ok"
        assert body["environment"] == "test"
        assert body["version"]

        database = next(d for d in body["dependencies"] if d["name"] == "database")
        assert database["healthy"] is True
        assert database["detail"] is None

    def test_reports_503_when_database_unreachable(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A dead database must degrade the health payload, not raise."""

        async def unreachable() -> tuple[bool, str | None]:
            return False, "cannot connect to database"

        monkeypatch.setattr("app.api.health.check_database", unreachable)

        with TestClient(create_app(settings)) as client:
            response = client.get("/health")

        assert response.status_code == 503
        body = response.json()
        assert body["status"] == "degraded"
        database = next(d for d in body["dependencies"] if d["name"] == "database")
        assert database["healthy"] is False
        assert database["detail"] == "cannot connect to database"

    def test_response_carries_request_id(self, client: TestClient) -> None:
        """Every response is correlatable to its log lines."""
        response = client.get("/health", headers={"x-request-id": "test-req-1"})

        assert response.headers["x-request-id"] == "test-req-1"

    def test_generates_request_id_when_absent(self, client: TestClient) -> None:
        response = client.get("/health")

        assert response.headers.get("x-request-id")


class TestResponseHardening:
    """Middleware that must apply to every response."""

    def test_security_headers_are_present(self, client: TestClient) -> None:
        response = client.get("/health")

        assert response.headers["x-content-type-options"] == "nosniff"
        assert response.headers["x-frame-options"] == "DENY"
        assert response.headers["referrer-policy"] == "no-referrer"

    def test_docs_are_served_outside_production(self, client: TestClient) -> None:
        assert client.get("/openapi.json").status_code == 200

    def test_docs_are_disabled_in_production(self, settings: Settings) -> None:
        """A deployed instance does not publish its schema."""
        production = settings.model_copy(
            update={"app_env": "production", "cors_origins": ["https://app.example"]}
        )

        with TestClient(create_app(production)) as client:
            assert client.get("/openapi.json").status_code == 404
            assert client.get("/docs").status_code == 404


class TestErrorContract:
    """Failures are returned in the documented envelope, never as tracebacks."""

    def test_unknown_route_returns_structured_error(self, client: TestClient) -> None:
        response = client.get("/api/does-not-exist")

        assert response.status_code == 404
        assert response.json()["error"]["code"] == "not_found"

    def test_app_error_is_rendered_in_envelope(self, settings: Settings) -> None:
        app = create_app(settings)

        @app.get("/boom")
        async def boom() -> None:
            raise DatabaseUnavailableError(session_id="abc")

        with TestClient(app) as client:
            response = client.get("/boom")

        assert response.status_code == 503
        assert response.json() == {
            "error": {
                "code": "database_unavailable",
                "message": (
                    "The knowledge store is temporarily unavailable. "
                    "Please try again."
                ),
            }
        }

    def test_unexpected_exception_does_not_leak_internals(
        self, settings: Settings
    ) -> None:
        """An unhandled error returns a generic message, not the exception text."""
        app = create_app(settings)

        @app.get("/explode")
        async def explode() -> None:
            raise RuntimeError("secret connection string postgres://user:pw@host")

        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.get("/explode")

        assert response.status_code == 500
        body = response.json()
        assert body["error"]["code"] == "internal_error"
        assert "secret" not in response.text
        assert "postgres://" not in response.text


class TestAppErrorType:
    """Unit-level behaviour of the error base class."""

    def test_context_is_not_serialised_to_client(self) -> None:
        error = AppError(code="x", message="safe message", internal_detail="sensitive")

        payload = error.to_response().model_dump()

        assert payload == {"error": {"code": "x", "message": "safe message"}}
        assert error.context == {"internal_detail": "sensitive"}

    def test_defaults_are_user_safe(self) -> None:
        error = AppError()

        assert error.status_code == 500
        assert error.code == "internal_error"
        assert "went wrong" in error.message
