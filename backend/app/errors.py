"""Application errors and the response contract.

Every failure reaching the client is rendered as:

    {"error": {"code": "provider_unavailable", "message": "..."}}

Internal detail (tracebacks, driver messages, prompts) is logged but never
returned. Codes live in constants.py because the frontend matches on them.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from app.constants import (
    ERROR_ARTIFACT_UNSAFE,
    ERROR_CONFIGURATION,
    ERROR_DATABASE_UNAVAILABLE,
    ERROR_EMBEDDING_FAILED,
    ERROR_INSUFFICIENT_EVIDENCE,
    ERROR_INTERNAL,
    ERROR_MODEL_FAILED,
    ERROR_MODEL_TIMEOUT,
    ERROR_NOT_FOUND,
    ERROR_PROVIDER_UNAVAILABLE,
)


class ErrorDetail(BaseModel):
    code: str
    message: str


class ErrorResponse(BaseModel):
    """Envelope returned for every non-2xx response."""

    error: ErrorDetail


class AppError(Exception):
    """A failure with a defined client-facing representation.

    `context` kwargs go to the log record only and are never serialised.
    """

    code = ERROR_INTERNAL
    message = "Something went wrong. Please try again."
    status_code = 500

    def __init__(
        self,
        message: str | None = None,
        *,
        code: str | None = None,
        status_code: int | None = None,
        **context: Any,
    ) -> None:
        if message is not None:
            self.message = message
        if code is not None:
            self.code = code
        if status_code is not None:
            self.status_code = status_code
        self.context = context
        super().__init__(self.message)

    def to_response(self) -> ErrorResponse:
        return ErrorResponse(error=ErrorDetail(code=self.code, message=self.message))


class ConfigurationError(AppError):
    code = ERROR_CONFIGURATION
    message = "The application is not correctly configured."
    status_code = 500


class DatabaseUnavailableError(AppError):
    code = ERROR_DATABASE_UNAVAILABLE
    message = "The knowledge store is temporarily unavailable. Please try again."
    status_code = 503


class NotFoundError(AppError):
    code = ERROR_NOT_FOUND
    message = "The requested resource was not found."
    status_code = 404


class EmbeddingError(AppError):
    code = ERROR_EMBEDDING_FAILED
    message = "We couldn't search the transcripts right now. Please try again."
    status_code = 503


class ProviderUnavailableError(AppError):
    """The selected model is not reachable, configured, or permitted here."""

    code = ERROR_PROVIDER_UNAVAILABLE
    message = "The selected model is currently unavailable."
    status_code = 503


class ModelTimeoutError(AppError):
    code = ERROR_MODEL_TIMEOUT
    message = "The model took too long to respond. Please try again."
    status_code = 504


class ModelError(AppError):
    code = ERROR_MODEL_FAILED
    message = "The model failed to generate a response. Please try again."
    status_code = 502


class InsufficientEvidenceError(AppError):
    """Too little relevant material to answer safely.

    A product outcome rather than a fault, so most flows return it in the
    normal response body; this exists for paths that must abort.
    """

    code = ERROR_INSUFFICIENT_EVIDENCE
    message = (
        "I couldn't find enough relevant material in Lenny's Podcast "
        "transcripts to answer this reliably."
    )
    status_code = 422


class ArtifactSecurityError(AppError):
    code = ERROR_ARTIFACT_UNSAFE
    message = (
        "This artifact could not be safely rendered. The generated content did "
        "not pass the application's safety checks."
    )
    status_code = 422
