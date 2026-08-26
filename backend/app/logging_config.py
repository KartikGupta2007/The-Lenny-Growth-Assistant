"""Structured logging.

Events are machine-readable names (retrieval_completed, model_request_started)
rather than free-form strings, so a failure can be traced across the
API -> agent -> retrieval -> model boundaries.
"""

from __future__ import annotations

import logging
import sys

import structlog

from app.config import Settings

# Keys whose value must never reach a log line, even if a caller binds them.
REDACTED_KEYS = frozenset(
    {
        "anthropic_api_key",
        "api_key",
        "authorization",
        "password",
        "database_url",
        "token",
    }
)


def _redact_secrets(
    _logger: object, _method: str, event_dict: dict[str, object]
) -> dict[str, object]:
    for key in list(event_dict):
        if key.lower() in REDACTED_KEYS:
            event_dict[key] = "***redacted***"
    return event_dict


def configure_logging(settings: Settings) -> None:
    """Console output in development, JSON everywhere else."""
    level = getattr(logging, settings.log_level.upper(), logging.INFO)

    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=level)
    # uvicorn installs its own handlers; keep them but align the level.
    for noisy in ("uvicorn.access", "uvicorn.error"):
        logging.getLogger(noisy).setLevel(level)

    renderer: structlog.typing.Processor = (
        structlog.dev.ConsoleRenderer(colors=True)
        if settings.app_env == "development"
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
    return structlog.get_logger(name)
