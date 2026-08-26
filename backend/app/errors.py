"""Application error types and the structured error contract.

Every failure that reaches the client is rendered as:

    {"error": {"code": "retrieval_unavailable", "message": "..."}}

Internal detail (stack traces, driver messages, prompts) is logged but never
returned to the caller, per PRD section 18.

The machine-readable ``code`` values live in ``app.constants`` because both
this module and the API layer emit them and the frontend matches on them. The
*message* stays here: it is user-facing copy that belongs to the exception it
describes.
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
    HTTP_BAD_GATEWAY,
    HTTP_GATEWAY_TIMEOUT,
    HTTP_INTERNAL_ERROR,
    HTTP_NOT_FOUND,
    HTTP_SERVICE_UNAVAILABLE,
    HTTP_UNPROCESSABLE,
)


class ErrorDetail(BaseModel):
    """Machine-readable error code plus a user-safe message."""

    code: str
    message: str


class ErrorResponse(BaseModel):
    """Envelope returned for every non-2xx response."""

    error: ErrorDetail


class AppError(Exception):
    """Base class for failures with a defined client-facing representation.

    Attributes:
        code: Stable machine-readable identifier for the failure class.
        message: Safe, user-facing description. Must not leak internals.
        status_code: HTTP status to return.
        context: Extra fields for the log record only; never serialised to the
            client.
    """

    code = ERROR_INTERNAL
    message = "Something went wrong. Please try again."
    status_code = HTTP_INTERNAL_ERROR

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
        """Render the client-facing envelope."""
        return ErrorResponse(error=ErrorDetail(code=self.code, message=self.message))


class ConfigurationError(AppError):
    """A required setting or credential is missing or invalid."""

    code = ERROR_CONFIGURATION
    message = "The application is not correctly configured."
    status_code = HTTP_INTERNAL_ERROR


class DatabaseUnavailableError(AppError):
    """PostgreSQL could not be reached."""

    code = ERROR_DATABASE_UNAVAILABLE
    message = "The knowledge store is temporarily unavailable. Please try again."
    status_code = HTTP_SERVICE_UNAVAILABLE


class NotFoundError(AppError):
    """A requested resource does not exist."""

    code = ERROR_NOT_FOUND
    message = "The requested resource was not found."
    status_code = HTTP_NOT_FOUND


class EmbeddingError(AppError):
    """The embedding provider failed to embed the query."""

    code = ERROR_EMBEDDING_FAILED
    message = "We couldn't search the transcripts right now. Please try again."
    status_code = HTTP_SERVICE_UNAVAILABLE


class ProviderUnavailableError(AppError):
    """The selected model provider is not reachable, configured or permitted."""

    code = ERROR_PROVIDER_UNAVAILABLE
    message = "The selected model is currently unavailable."
    status_code = HTTP_SERVICE_UNAVAILABLE


class ModelTimeoutError(AppError):
    """The model did not respond within the configured timeout."""

    code = ERROR_MODEL_TIMEOUT
    message = "The model took too long to respond. Please try again."
    status_code = HTTP_GATEWAY_TIMEOUT


class ModelError(AppError):
    """The model provider returned an error."""

    code = ERROR_MODEL_FAILED
    message = "The model failed to generate a response. Please try again."
    status_code = HTTP_BAD_GATEWAY


class InsufficientEvidenceError(AppError):
    """Retrieval produced too little relevant material to answer safely.

    This is a *product* outcome rather than a fault, so it is surfaced through
    the normal response body rather than raised in most flows; the exception
    exists for the paths that must abort (for example essay generation, which
    cannot be grounded without evidence).
    """

    code = ERROR_INSUFFICIENT_EVIDENCE
    message = (
        "I couldn't find enough relevant material in Lenny's Podcast "
        "transcripts to answer this reliably."
    )
    status_code = HTTP_UNPROCESSABLE


class ArtifactSecurityError(AppError):
    """Generated artifact content failed the sanitisation stage."""

    code = ERROR_ARTIFACT_UNSAFE
    message = (
        "This artifact could not be safely rendered. The generated content did "
        "not pass the application's safety checks."
    )
    status_code = HTTP_UNPROCESSABLE
