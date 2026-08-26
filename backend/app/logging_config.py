"""Structured logging setup.

The application emits machine-readable event logs (``retrieval_completed``,
``model_request_started``, ...) rather than free-form strings, so that a
failure can be traced across the API -> agent -> retrieval -> model boundaries.

Secrets are never passed to the logger; provider modules log the *name* of a
credential-bearing setting, never its value.
"""

from __future__ import annotations

import logging
import sys

import structlog

from app.config import Settings
from app.constants import (
    ENV_DEVELOPMENT,
    LOG_FORMAT,
    REDACTED,
    REDACTED_KEYS,
    UVICORN_LOGGERS,
)


def _redact_secrets(
    _logger: object, _method: str, event_dict: dict[str, object]
) -> dict[str, object]:
    """Replace any value bound under a known-sensitive key."""
    for key in list(event_dict):
        if key.lower() in REDACTED_KEYS:
            event_dict[key] = REDACTED
    return event_dict


def configure_logging(settings: Settings) -> None:
    """Configure structlog and the stdlib root logger.

    Development renders human-readable console output; every other environment
    renders JSON so logs can be shipped and queried.
    """
    level = getattr(logging, settings.log_level.upper(), logging.INFO)

    logging.basicConfig(format=LOG_FORMAT, stream=sys.stdout, level=level)
    # uvicorn installs its own handlers; keep them but align the level.
    for noisy in UVICORN_LOGGERS:
        logging.getLogger(noisy).setLevel(level)

    renderer: structlog.typing.Processor = (
        structlog.dev.ConsoleRenderer(colors=True)
        if settings.app_env == ENV_DEVELOPMENT
        else structlog.processors.JSONRenderer()
    )

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            _redact_secrets,
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """Return a bound structlog logger for ``name``."""
    return structlog.get_logger(name)