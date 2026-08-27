"""FastAPI application factory.

Logging, middleware, exception handling and router registration only.
Retrieval, model access and persistence live in their own packages.
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

from app.api import artifacts, health, providers, sessions
from app.config import Settings, get_settings
from app.constants import (
    ERROR_HTTP,
    ERROR_INTERNAL,
    ERROR_NOT_FOUND,
    ERROR_VALIDATION,
    ROUTE_HEALTH,
)
from app.db.session import get_engine
from app.errors import AppError, ErrorDetail, ErrorResponse
from app.http import close_http_client
from app.logging_config import configure_logging, get_logger
from app.models.registry import get_provider_registry

logger = get_logger(__name__)

CallNext = Callable[[Request], Awaitable[Response]]

# A JSON API serves no HTML; these just stop a browser sniffing a response
# into something executable.
SECURITY_HEADERS = {
    "x-content-type-options": "nosniff",
    "referrer-policy": "no-referrer",
    "x-frame-options": "DENY",
}


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings: Settings = app.state.settings
    logger.info(
        "application_started",
        environment=settings.app_env,
        version=settings.app_version,
        llm_provider=settings.llm_provider,
        local_providers_enabled=settings.local_providers_enabled,
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
    payload = ErrorResponse(error=ErrorDetail(code=code, message=message))
    return JSONResponse(status_code=status_code, content=payload.model_dump())


def register_exception_handlers(app: FastAPI) -> None:
    """Ensure no failure escapes as an untyped 500 or a traceback."""

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
            422, ERROR_VALIDATION, "The request was not valid. Please check your input."
        )

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_error(
        _request: Request, exc: StarletteHTTPException
    ) -> JSONResponse:
        code = ERROR_NOT_FOUND if exc.status_code == 404 else ERROR_HTTP
        detail = exc.detail if isinstance(exc.detail, str) else "Request failed."
        return _error_response(exc.status_code, code, detail)

    @app.exception_handler(Exception)
    async def handle_unexpected(_request: Request, exc: Exception) -> JSONResponse:
        # Log the traceback, return nothing internal.
        logger.error("unhandled_error", error=str(exc), exc_info=True)
        return _error_response(
            500, ERROR_INTERNAL, "Something went wrong. Please try again."
        )


def register_middleware(app: FastAPI, settings: Settings) -> None:
    """Install middleware.

    Starlette runs the most recently added first, so CORS is registered last
    and wraps everything: an error response still carries the headers the
    browser needs in order to let the frontend read the error body.
    """

    @app.middleware("http")
    async def add_security_headers(request: Request, call_next: CallNext) -> Response:
        response = await call_next(request)
        for header, value in SECURITY_HEADERS.items():
            response.headers.setdefault(header, value)
        return response

    @app.middleware("http")
    async def bind_request_context(request: Request, call_next: CallNext) -> Response:
        """Bind a request id so every log line in the request correlates."""
        request_id = request.headers.get("x-request-id") or uuid.uuid4().hex
        # Health is polled constantly; keep it out of the log at info level.
        log = logger.debug if request.url.path == ROUTE_HEALTH else logger.info

        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(
            request_id=request_id, method=request.method, path=request.url.path
        )
        started = time.perf_counter()
        log("request_started")
        try:
            response = await call_next(request)
        except Exception:
            logger.error(
                "request_errored",
                duration_ms=round((time.perf_counter() - started) * 1000, 2),
            )
            raise
        finally:
            # Never leak this request's context into the next one.
            structlog.contextvars.unbind_contextvars("request_id", "method", "path")

        log(
            "request_completed",
            status_code=response.status_code,
            duration_ms=round((time.perf_counter() - started) * 1000, 2),
        )
        response.headers["x-request-id"] = request_id
        return response

    if settings.allowed_hosts != ["*"]:
        app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.allowed_hosts)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
        allow_headers=["*"],
        expose_headers=["x-request-id"],
        max_age=600,
    )


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings)

    docs_enabled = settings.docs_enabled
    app = FastAPI(
        title="Lenny Growth Assistant API",
        description="Conversational assistant grounded in Lenny's Podcast transcripts.",
        version=settings.app_version,
        lifespan=lifespan,
        docs_url="/docs" if docs_enabled else None,
        redoc_url="/redoc" if docs_enabled else None,
        openapi_url="/openapi.json" if docs_enabled else None,
    )
    app.state.settings = settings
    app.state.provider_registry = get_provider_registry()

    register_middleware(app, settings)
    register_exception_handlers(app)

    # Health sits at the root so probes need no knowledge of the API prefix.
    app.include_router(health.router)
    app.include_router(providers.router, prefix=settings.api_prefix)
    app.include_router(sessions.router, prefix=settings.api_prefix)
    app.include_router(artifacts.router, prefix=settings.api_prefix)

    return app


app = create_app()
