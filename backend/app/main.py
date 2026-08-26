"""FastAPI application factory and wiring.

This module is deliberately thin: it configures logging, middleware, exception
handling and router registration. Retrieval, model access, ingestion and
artifact security all live in their own packages and are never implemented
here.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.api import health, providers
from app.config import Settings, get_settings
from app.constants import (
    ALLOWED_HTTP_METHODS,
    APP_DESCRIPTION,
    APP_TITLE,
    CORS_MAX_AGE_SECONDS,
    DEFAULT_ALLOWED_HOSTS,
    DOCS_URL,
    ERROR_HTTP,
    ERROR_INTERNAL,
    ERROR_NOT_FOUND,
    ERROR_VALIDATION,
    HEADER_REQUEST_ID,
    HTTP_INTERNAL_ERROR,
    HTTP_NOT_FOUND,
    HTTP_UNPROCESSABLE,
    OPENAPI_URL,
    QUIET_PATHS,
    REDOC_URL,
    SECURITY_HEADERS,
    WILDCARD,
)
from app.db.session import get_engine
from app.errors import AppError, ErrorDetail, ErrorResponse
from app.http import close_http_client
from app.logging_config import configure_logging, get_logger
from app.models.registry import get_provider_registry

logger = get_logger(__name__)

CallNext = Callable[[Request], Awaitable[Response]]


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Log startup/shutdown and release shared resources on exit."""
    settings: Settings = app.state.settings
    logger.info(
        "application_started",
        environment=settings.app_env,
        version=settings.app_version,
        llm_provider=settings.llm_provider,
        local_providers_enabled=settings.local_providers_enabled,
        embedding_provider=settings.embedding_provider,
        embedding_model=settings.embedding_model,
        docs_enabled=settings.docs_enabled,
    )
    try:
        yield
    finally:
        await close_http_client()
        await get_engine().dispose()
        logger.info("application_stopped")


def _error_response(status_code: int, code: str, message: str) -> JSONResponse:
    """Build the standard error envelope."""
    payload = ErrorResponse(error=ErrorDetail(code=code, message=message))
    return JSONResponse(status_code=status_code, content=payload.model_dump())


def register_exception_handlers(app: FastAPI) -> None:
    """Install handlers so no failure escapes as an untyped 500 or traceback."""

    @app.exception_handler(AppError)
    async def handle_app_error(_request: Request, exc: AppError) -> JSONResponse:
        logger.warning(
            "request_failed",
            code=exc.code,
            status_code=exc.status_code,
            **exc.context,
        )
        return _error_response(exc.status_code, exc.code, exc.message)

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        _request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        logger.info("request_invalid", errors=exc.errors())
        return _error_response(
            HTTP_UNPROCESSABLE,
            ERROR_VALIDATION,
            "The request was not valid. Please check your input.",
        )

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_error(
        _request: Request, exc: StarletteHTTPException
    ) -> JSONResponse:
        code = ERROR_NOT_FOUND if exc.status_code == HTTP_NOT_FOUND else ERROR_HTTP
        detail = exc.detail if isinstance(exc.detail, str) else "Request failed."
        return _error_response(exc.status_code, code, detail)

    @app.exception_handler(Exception)
    async def handle_unexpected(_request: Request, exc: Exception) -> JSONResponse:
        # Log the full traceback, return nothing internal to the caller.
        logger.error("unhandled_error", error=str(exc), exc_info=True)
        return _error_response(
            HTTP_INTERNAL_ERROR,
            ERROR_INTERNAL,
            "Something went wrong. Please try again.",
        )


def register_middleware(app: FastAPI, settings: Settings) -> None:
    """Install middleware.

    Order matters: Starlette runs the most recently added middleware first, so
    CORS is registered last and therefore wraps everything else. That way an
    error response still carries the CORS headers the browser needs in order
    to let the frontend read the error body at all.
    """

    @app.middleware("http")
    async def add_security_headers(request: Request, call_next: CallNext) -> Response:
        """Defensive headers for a JSON API.

        The API serves no HTML, so the goal is simply that a browser never
        sniffs a response into something executable.
        """
        response = await call_next(request)
        for header, value in SECURITY_HEADERS.items():
            response.headers.setdefault(header, value)
        return response

    @app.middleware("http")
    async def bind_request_context(request: Request, call_next: CallNext) -> Response:
        """Bind a request id so every log line in the request is correlatable."""
        request_id = request.headers.get(HEADER_REQUEST_ID) or uuid.uuid4().hex
        quiet = request.url.path in QUIET_PATHS

        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(
            request_id=request_id,
            method=request.method,
            path=request.url.path,
        )
        started = time.perf_counter()
        log = logger.debug if quiet else logger.info
        log("request_started")
        try:
            response = await call_next(request)
        except Exception:
            # The exception handler renders the body; record the timing here
            # because that handler cannot see when the request began.
            logger.error(
                "request_errored",
                duration_ms=round((time.perf_counter() - started) * 1000, 2),
            )
            raise
        finally:
            # Never leak this request's context into the next one handled by
            # the same worker task.
            structlog.contextvars.unbind_contextvars("request_id", "method", "path")

        log(
            "request_completed",
            status_code=response.status_code,
            duration_ms=round((time.perf_counter() - started) * 1000, 2),
        )
        response.headers[HEADER_REQUEST_ID] = request_id
        return response

    if settings.allowed_hosts != list(DEFAULT_ALLOWED_HOSTS):
        app.add_middleware(
            TrustedHostMiddleware, allowed_hosts=settings.allowed_hosts
        )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=False,
        allow_methods=list(ALLOWED_HTTP_METHODS),
        allow_headers=[WILDCARD],
        expose_headers=[HEADER_REQUEST_ID],
        max_age=CORS_MAX_AGE_SECONDS,
    )


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build and configure the FastAPI application."""
    settings = settings or get_settings()
    configure_logging(settings)

    # Interactive docs are development affordances; a deployed instance does
    # not need to publish its schema.
    docs_enabled = settings.docs_enabled
    app = FastAPI(
        title=APP_TITLE,
        description=APP_DESCRIPTION,
        version=settings.app_version,
        lifespan=lifespan,
        docs_url=DOCS_URL if docs_enabled else None,
        redoc_url=REDOC_URL if docs_enabled else None,
        openapi_url=OPENAPI_URL if docs_enabled else None,
    )
    app.state.settings = settings
    # Registries are process-wide singletons; exposing them on app.state keeps
    # them overridable in tests via dependency_overrides.
    app.state.provider_registry = get_provider_registry()

    register_middleware(app, settings)
    register_exception_handlers(app)

    # Health lives at the root so probes need no knowledge of the API prefix;
    # product resources live under the configured prefix.
    app.include_router(health.router)
    app.include_router(providers.router, prefix=settings.api_prefix)

    return app


app = create_app()
