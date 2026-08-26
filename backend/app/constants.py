"""Single source of truth for every fixed value in the backend.

Nothing here imports from the rest of ``app``, so this module can be imported
from anywhere without a cycle. The rule the codebase follows:

* A value that appears in more than one module, or that a reader would have to
  guess the meaning of at its call site, is named here.
* User-facing *prose* stays with the code that owns it -- error copy lives on
  the exception class in ``app.errors``, because the message is part of that
  class's contract. Only the machine-readable ``code`` is defined here, since
  those codes are matched by both the API layer and the frontend.

Mutable containers are declared as tuples/frozensets so a caller cannot mutate
shared state by accident; the settings layer copies them into lists where
pydantic needs a mutable default.
"""

from __future__ import annotations

from pathlib import Path
from typing import Final, Literal

# ---------------------------------------------------------------------------
# Application identity
# ---------------------------------------------------------------------------

APP_NAME: Final = "lenny-growth-assistant"
APP_TITLE: Final = "Lenny Growth Assistant API"
APP_DESCRIPTION: Final = (
    "Conversational assistant grounded in Lenny's Podcast transcripts."
)
DEFAULT_APP_VERSION: Final = "0.1.0"

# backend/ -- the directory that owns .env, requirements.txt and pytest.ini.
BACKEND_DIR: Final[Path] = Path(__file__).resolve().parent.parent
ENV_FILE: Final[Path] = BACKEND_DIR / ".env"

# ---------------------------------------------------------------------------
# Environments
# ---------------------------------------------------------------------------

Environment = Literal["development", "test", "production"]

ENV_DEVELOPMENT: Final[Environment] = "development"
ENV_TEST: Final[Environment] = "test"
ENV_PRODUCTION: Final[Environment] = "production"

DEFAULT_APP_ENV: Final[Environment] = ENV_DEVELOPMENT

# ---------------------------------------------------------------------------
# Providers
#
# The ids are part of the API contract: they appear in GET /api/providers and
# in the LLM_PROVIDER environment variable, and the frontend switches on them.
# ---------------------------------------------------------------------------

LLMProviderId = Literal["ollama", "anthropic"]
ProviderKind = Literal["local", "cloud"]

# Embeddings are always generated locally by Ollama. This stays a Literal
# rather than a bare string so that setting EMBEDDING_PROVIDER to anything
# else fails at startup with a clear message, instead of being ignored -- and
# so the seam is still here if a second provider is ever added.
EmbeddingProviderId = Literal["ollama"]

PROVIDER_OLLAMA: Final[LLMProviderId] = "ollama"
PROVIDER_ANTHROPIC: Final[LLMProviderId] = "anthropic"

EMBEDDING_PROVIDER_OLLAMA: Final[EmbeddingProviderId] = "ollama"

KIND_LOCAL: Final[ProviderKind] = "local"
KIND_CLOUD: Final[ProviderKind] = "cloud"

# Display names shown in the model selector.
LABEL_OLLAMA: Final = "Ollama"
LABEL_ANTHROPIC: Final = "Claude"

DEFAULT_LLM_PROVIDER: Final[LLMProviderId] = PROVIDER_OLLAMA
DEFAULT_EMBEDDING_PROVIDER: Final[EmbeddingProviderId] = EMBEDDING_PROVIDER_OLLAMA

# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

DEFAULT_API_PREFIX: Final = "/api"
ROUTE_HEALTH: Final = "/health"
ROUTE_PROVIDERS: Final = "/providers"

DOCS_URL: Final = "/docs"
REDOC_URL: Final = "/redoc"
OPENAPI_URL: Final = "/openapi.json"

TAG_HEALTH: Final = "health"
TAG_PROVIDERS: Final = "providers"

# Paths logged at debug level. Liveness probes would otherwise dominate the
# log volume of a deployed instance.
QUIET_PATHS: Final[frozenset[str]] = frozenset({ROUTE_HEALTH})

# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------

HEADER_REQUEST_ID: Final = "x-request-id"

ALLOWED_HTTP_METHODS: Final[tuple[str, ...]] = ("GET", "POST", "DELETE", "OPTIONS")
CORS_MAX_AGE_SECONDS: Final = 600
WILDCARD: Final = "*"

# Defensive headers for a JSON API. The API serves no HTML, so the goal is
# simply that a browser never sniffs a response into something executable.
SECURITY_HEADERS: Final[dict[str, str]] = {
    "x-content-type-options": "nosniff",
    "referrer-policy": "no-referrer",
    "x-frame-options": "DENY",
}

USER_AGENT_TEMPLATE: Final = APP_NAME + "/{version}"

DEFAULT_HTTP_MAX_CONNECTIONS: Final = 20

# ---------------------------------------------------------------------------
# Error codes
#
# Stable machine-readable identifiers. The frontend matches on these, so they
# are treated as an API contract and changed only deliberately.
# ---------------------------------------------------------------------------

ERROR_INTERNAL: Final = "internal_error"
ERROR_CONFIGURATION: Final = "configuration_error"
ERROR_DATABASE_UNAVAILABLE: Final = "database_unavailable"
ERROR_NOT_FOUND: Final = "not_found"
ERROR_VALIDATION: Final = "validation_error"
ERROR_HTTP: Final = "http_error"
ERROR_EMBEDDING_FAILED: Final = "embedding_failed"
ERROR_PROVIDER_UNAVAILABLE: Final = "provider_unavailable"
ERROR_MODEL_TIMEOUT: Final = "model_timeout"
ERROR_MODEL_FAILED: Final = "model_error"
ERROR_INSUFFICIENT_EVIDENCE: Final = "insufficient_evidence"
ERROR_ARTIFACT_UNSAFE: Final = "artifact_unsafe"

# ---------------------------------------------------------------------------
# HTTP status codes used by the error layer
# ---------------------------------------------------------------------------

HTTP_BAD_GATEWAY: Final = 502
HTTP_GATEWAY_TIMEOUT: Final = 504
HTTP_INTERNAL_ERROR: Final = 500
HTTP_NOT_FOUND: Final = 404
HTTP_SERVICE_UNAVAILABLE: Final = 503
HTTP_UNPROCESSABLE: Final = 422

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

DEFAULT_LOG_LEVEL: Final = "INFO"
VALID_LOG_LEVELS: Final[frozenset[str]] = frozenset(
    {"CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG", "NOTSET"}
)
LOG_FORMAT: Final = "%(message)s"
REDACTED: Final = "***redacted***"

# Keys whose value must never reach a log line, even if a caller binds them.
REDACTED_KEYS: Final[frozenset[str]] = frozenset(
    {
        "anthropic_api_key",
        "api_key",
        "authorization",
        "password",
        "database_url",
        "token",
    }
)

# uvicorn installs its own handlers; these are aligned to the app's level.
UVICORN_LOGGERS: Final[tuple[str, ...]] = ("uvicorn.access", "uvicorn.error")

# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

DEFAULT_DATABASE_URL: Final = (
    "postgresql+psycopg://localhost:5432/lenny_growth_assistant"
)

ASYNC_DRIVER_PREFIX: Final = "postgresql+psycopg://"
BARE_POSTGRES_PREFIX: Final = "postgresql://"
ASYNCPG_DRIVER_FRAGMENT: Final = "+asyncpg"
PSYCOPG_DRIVER_FRAGMENT: Final = "+psycopg"

DB_POOL_SIZE: Final = 5
DB_MAX_OVERFLOW: Final = 5

PGVECTOR_EXTENSION: Final = "vector"
SQL_PING: Final = "SELECT 1"
SQL_PGVECTOR_INSTALLED: Final = (
    f"SELECT 1 FROM pg_extension WHERE extname = '{PGVECTOR_EXTENSION}'"
)

DEFAULT_DATABASE_PROBE_TIMEOUT_SECONDS: Final = 3.0

# ---------------------------------------------------------------------------
# Ollama
# ---------------------------------------------------------------------------

DEFAULT_OLLAMA_BASE_URL: Final = "http://localhost:11434"
DEFAULT_OLLAMA_MODEL: Final = "llama3.1:8b"
DEFAULT_OLLAMA_TIMEOUT_SECONDS: Final = 180.0

OLLAMA_TAGS_PATH: Final = "/api/tags"
OLLAMA_MODELS_KEY: Final = "models"
OLLAMA_MODEL_NAME_KEY: Final = "name"
# Ollama reports `nomic-embed-text:latest` for a model pulled untagged.
OLLAMA_TAG_SEPARATOR: Final = ":"
OLLAMA_DEFAULT_TAG: Final = "latest"

# ---------------------------------------------------------------------------
# Anthropic
# ---------------------------------------------------------------------------

DEFAULT_ANTHROPIC_MODEL: Final = "claude-sonnet-5"
DEFAULT_ANTHROPIC_TIMEOUT_SECONDS: Final = 120.0

# ---------------------------------------------------------------------------
# Provider availability probing
#
# Probes run on the request path, so the timeout is short and the result is
# cached for the TTL below.
# ---------------------------------------------------------------------------

DEFAULT_PROVIDER_PROBE_TIMEOUT_SECONDS: Final = 3.0
DEFAULT_PROVIDER_STATUS_TTL_SECONDS: Final = 15.0

# ---------------------------------------------------------------------------
# Embeddings
#
# Embeddings are generated locally by Ollama, so the corpus can be ingested
# with no API key, no cloud egress and no per-token cost.
#
# EMBEDDING_DIMENSIONS holds the native output width per model. It sizes the
# pgvector column, so an unmapped model must fail loudly rather than default
# to a wrong width -- and changing the model requires a re-ingest.
# ---------------------------------------------------------------------------

DEFAULT_EMBEDDING_MODEL: Final = "nomic-embed-text"
DEFAULT_EMBEDDING_BATCH_SIZE: Final = 32
DEFAULT_EMBEDDING_TIMEOUT_SECONDS: Final = 120.0

EMBEDDING_DIMENSIONS: Final[dict[str, int]] = {
    "nomic-embed-text": 768,
    "mxbai-embed-large": 1024,
}

# ---------------------------------------------------------------------------
# Ingestion
# ---------------------------------------------------------------------------

DEFAULT_TRANSCRIPT_REPO: Final = "ChatPRD/lennys-podcast-transcripts"
DEFAULT_TRANSCRIPT_REPO_REF: Final = "main"
DEFAULT_TRANSCRIPT_CACHE_DIR: Final = ".transcript-cache"
DEFAULT_CHUNK_TARGET_TOKENS: Final = 600
DEFAULT_CHUNK_OVERLAP_TOKENS: Final = 80

# ---------------------------------------------------------------------------
# Retrieval
# ---------------------------------------------------------------------------

DEFAULT_RETRIEVAL_TOP_K: Final = 8
# Cosine distance above which a chunk is treated as irrelevant. Chunks that do
# not clear this bar are dropped, which is what drives the "insufficient
# evidence" response instead of a fabricated answer.
DEFAULT_RETRIEVAL_MAX_DISTANCE: Final = 0.62
MAX_COSINE_DISTANCE: Final = 2.0
# Minimum number of surviving chunks required to attempt a grounded answer.
DEFAULT_RETRIEVAL_MIN_CHUNKS: Final = 2

# ---------------------------------------------------------------------------
# Frontend / CORS
# ---------------------------------------------------------------------------

# The Vite dev server.
DEFAULT_CORS_ORIGINS: Final[tuple[str, ...]] = (
    "http://localhost:5173",
    "http://127.0.0.1:5173",
)
DEFAULT_ALLOWED_HOSTS: Final[tuple[str, ...]] = (WILDCARD,)
