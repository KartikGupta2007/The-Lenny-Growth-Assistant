"""Environment-driven application configuration.

All tunable behaviour of the backend is expressed here so that no module needs
to read ``os.environ`` directly. Every literal default comes from
``app.constants``; this module owns *how* settings are parsed and validated,
not *what* the values are.

Secrets are held as ``SecretStr`` so that an accidental ``repr``/log of the
settings object cannot leak them, and are only unwrapped at the point of use.

The ``.env`` file is resolved relative to the ``backend/`` package rather than
the process working directory, so ``uvicorn app.main:app`` behaves identically
whether it is launched from the repository root or from ``backend/``.
"""

from __future__ import annotations

import json
from functools import lru_cache
from typing import Annotated

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

from app.constants import (
    DEFAULT_ALLOWED_HOSTS,
    DEFAULT_ANTHROPIC_MODEL,
    DEFAULT_ANTHROPIC_TIMEOUT_SECONDS,
    DEFAULT_API_PREFIX,
    DEFAULT_APP_ENV,
    DEFAULT_APP_VERSION,
    DEFAULT_CHUNK_OVERLAP_TOKENS,
    DEFAULT_CHUNK_TARGET_TOKENS,
    DEFAULT_CORS_ORIGINS,
    DEFAULT_DATABASE_PROBE_TIMEOUT_SECONDS,
    DEFAULT_DATABASE_URL,
    DEFAULT_EMBEDDING_BATCH_SIZE,
    DEFAULT_EMBEDDING_MODEL,
    DEFAULT_EMBEDDING_PROVIDER,
    DEFAULT_EMBEDDING_TIMEOUT_SECONDS,
    DEFAULT_HTTP_MAX_CONNECTIONS,
    DEFAULT_LLM_PROVIDER,
    DEFAULT_LOG_LEVEL,
    DEFAULT_OLLAMA_BASE_URL,
    DEFAULT_OLLAMA_MODEL,
    DEFAULT_OLLAMA_TIMEOUT_SECONDS,
    DEFAULT_PROVIDER_PROBE_TIMEOUT_SECONDS,
    DEFAULT_PROVIDER_STATUS_TTL_SECONDS,
    DEFAULT_RETRIEVAL_MAX_DISTANCE,
    DEFAULT_RETRIEVAL_MIN_CHUNKS,
    DEFAULT_RETRIEVAL_TOP_K,
    DEFAULT_TRANSCRIPT_CACHE_DIR,
    DEFAULT_TRANSCRIPT_REPO,
    DEFAULT_TRANSCRIPT_REPO_REF,
    EMBEDDING_DIMENSIONS,
    ENV_FILE,
    ENV_PRODUCTION,
    MAX_COSINE_DISTANCE,
    PSYCOPG_DRIVER_FRAGMENT,
    VALID_LOG_LEVELS,
    WILDCARD,
    ASYNCPG_DRIVER_FRAGMENT,
    EmbeddingProviderId,
    Environment,
    LLMProviderId,
)


class Settings(BaseSettings):
    """Backend settings, loaded from the environment and ``backend/.env``."""

    model_config = SettingsConfigDict(
        env_file=ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
        # `.env.example` ships keys with no value (DATABASE_URL=,
        # ANTHROPIC_API_KEY=) as placeholders. Without this, copying it to
        # .env would set them to "" and override the defaults with an invalid
        # DSN and an empty credential. An empty value means "unset".
        env_ignore_empty=True,
    )

    # ---- Application ----
    app_env: Environment = DEFAULT_APP_ENV
    app_version: str = DEFAULT_APP_VERSION
    log_level: str = DEFAULT_LOG_LEVEL
    api_prefix: str = DEFAULT_API_PREFIX

    # ``NoDecode`` stops pydantic-settings from JSON-decoding the raw value
    # before validation, so the documented comma-separated form in
    # .env.example parses instead of raising a JSONDecodeError at startup.
    cors_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: list(DEFAULT_CORS_ORIGINS)
    )
    # Host header allow-list. "*" is acceptable behind a trusted proxy that
    # already terminates and validates the host; set it explicitly otherwise.
    allowed_hosts: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: list(DEFAULT_ALLOWED_HOSTS)
    )
    # Interactive API docs. ``None`` means "on everywhere except production".
    enable_docs: bool | None = None

    # ---- Database ----
    # No username: psycopg falls back to the OS user, which is how a Homebrew
    # PostgreSQL install is provisioned. Managed/Linux instances usually need
    # an explicit ``user:password@`` prefix.
    database_url: str = DEFAULT_DATABASE_URL
    # Health checks must never hang behind a dead socket.
    database_probe_timeout_seconds: float = Field(
        default=DEFAULT_DATABASE_PROBE_TIMEOUT_SECONDS, gt=0
    )

    # ---- LLM providers ----
    # Which provider generates by default. The frontend may override this
    # per-request, but the server only honours a provider that is actually
    # selectable in this environment (see app/models/registry.py).
    llm_provider: LLMProviderId = DEFAULT_LLM_PROVIDER

    # Local providers (Ollama) are unavailable in production by default: the
    # hosted environment has no GPU/RAM budget for a local model, per
    # architecture.md section 22. ``None`` means "derive from app_env"; set it
    # explicitly to true for a self-hosted deployment that does run Ollama.
    enable_local_providers: bool | None = None

    ollama_base_url: str = DEFAULT_OLLAMA_BASE_URL
    ollama_model: str = DEFAULT_OLLAMA_MODEL
    ollama_timeout_seconds: float = Field(
        default=DEFAULT_OLLAMA_TIMEOUT_SECONDS, gt=0
    )

    anthropic_api_key: SecretStr | None = None
    anthropic_model: str = DEFAULT_ANTHROPIC_MODEL
    anthropic_timeout_seconds: float = Field(
        default=DEFAULT_ANTHROPIC_TIMEOUT_SECONDS, gt=0
    )

    # Availability probing. Probes run on the request path, so they use a short
    # timeout and their result is cached for the TTL below.
    provider_probe_timeout_seconds: float = Field(
        default=DEFAULT_PROVIDER_PROBE_TIMEOUT_SECONDS, gt=0
    )
    provider_status_ttl_seconds: float = Field(
        default=DEFAULT_PROVIDER_STATUS_TTL_SECONDS, ge=0
    )

    # ---- Embedding provider ----
    # Always Ollama: embeddings stay local, so ingesting the corpus needs no
    # API key and costs nothing. This is independent of LLM_PROVIDER, which
    # may still be a cloud model.
    embedding_provider: EmbeddingProviderId = DEFAULT_EMBEDDING_PROVIDER
    embedding_model: str = DEFAULT_EMBEDDING_MODEL
    embedding_batch_size: int = Field(default=DEFAULT_EMBEDDING_BATCH_SIZE, gt=0)
    embedding_timeout_seconds: float = Field(
        default=DEFAULT_EMBEDDING_TIMEOUT_SECONDS, gt=0
    )

    # ---- Knowledge base / ingestion ----
    transcript_repo: str = DEFAULT_TRANSCRIPT_REPO
    transcript_repo_ref: str = DEFAULT_TRANSCRIPT_REPO_REF
    transcript_cache_dir: str = DEFAULT_TRANSCRIPT_CACHE_DIR
    chunk_target_tokens: int = Field(default=DEFAULT_CHUNK_TARGET_TOKENS, gt=0)
    chunk_overlap_tokens: int = Field(default=DEFAULT_CHUNK_OVERLAP_TOKENS, ge=0)

    # ---- Retrieval ----
    retrieval_top_k: int = Field(default=DEFAULT_RETRIEVAL_TOP_K, gt=0)
    retrieval_max_distance: float = Field(
        default=DEFAULT_RETRIEVAL_MAX_DISTANCE, gt=0, le=MAX_COSINE_DISTANCE
    )
    retrieval_min_chunks: int = Field(default=DEFAULT_RETRIEVAL_MIN_CHUNKS, gt=0)

    # ---- Outbound HTTP ----
    http_max_connections: int = Field(default=DEFAULT_HTTP_MAX_CONNECTIONS, gt=0)

    @field_validator("cors_origins", "allowed_hosts", mode="before")
    @classmethod
    def _split_list(cls, value: object) -> object:
        """Accept a comma-separated string, a JSON array, or a real list.

        Environment variables are strings, and both ``a,b`` and ``["a","b"]``
        are natural things to write in a .env file or a deployment console, so
        both are accepted rather than only the JSON form.
        """
        if not isinstance(value, str):
            return value
        text = value.strip()
        if text.startswith("["):
            try:
                return json.loads(text)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Malformed JSON list: {value!r}") from exc
        return [item.strip() for item in text.split(",") if item.strip()]

    @field_validator("log_level")
    @classmethod
    def _validate_log_level(cls, value: str) -> str:
        """Reject a misspelled level instead of silently falling back to INFO."""
        level = value.upper()
        if level not in VALID_LOG_LEVELS:
            known = ", ".join(sorted(VALID_LOG_LEVELS))
            raise ValueError(f"Invalid LOG_LEVEL {value!r}. Expected one of: {known}")
        return level

    @field_validator("api_prefix")
    @classmethod
    def _normalise_prefix(cls, value: str) -> str:
        """Guarantee a leading slash and no trailing slash."""
        prefix = "/" + value.strip("/")
        return "" if prefix == "/" else prefix

    @field_validator("ollama_base_url")
    @classmethod
    def _strip_trailing_slash(cls, value: str) -> str:
        return value.rstrip("/")

    @field_validator("chunk_overlap_tokens")
    @classmethod
    def _overlap_fits_in_chunk(cls, value: int, info) -> int:  # type: ignore[no-untyped-def]
        """Overlap >= chunk size would loop forever during chunking."""
        target = info.data.get("chunk_target_tokens")
        if target is not None and value >= target:
            raise ValueError(
                "CHUNK_OVERLAP_TOKENS must be smaller than CHUNK_TARGET_TOKENS"
            )
        return value

    @model_validator(mode="after")
    def _production_guardrails(self) -> Settings:
        """Fail fast on configurations that are unsafe once deployed."""
        if self.app_env != ENV_PRODUCTION:
            return self
        if WILDCARD in self.cors_origins:
            raise ValueError(
                "CORS_ORIGINS must list explicit origins in production; "
                f"{WILDCARD!r} would let any site call the API."
            )
        return self

    # ---- Derived values ----

    @property
    def is_production(self) -> bool:
        """Whether this process is running as a deployed instance."""
        return self.app_env == ENV_PRODUCTION

    @property
    def docs_enabled(self) -> bool:
        """Whether /docs, /redoc and /openapi.json are served."""
        if self.enable_docs is not None:
            return self.enable_docs
        return not self.is_production

    @property
    def local_providers_enabled(self) -> bool:
        """Whether locally hosted model providers may be selected at all.

        This is a *policy* decision, distinct from whether Ollama happens to be
        reachable. In production the local provider is reported to the UI but
        marked unselectable, so the option stays visible and explained rather
        than silently disappearing.
        """
        if self.enable_local_providers is not None:
            return self.enable_local_providers
        return not self.is_production

    @property
    def embedding_dimensions(self) -> int:
        """Vector width for the configured embedding model."""
        try:
            return EMBEDDING_DIMENSIONS[self.embedding_model]
        except KeyError as exc:  # pragma: no cover - configuration error path
            known = ", ".join(sorted(EMBEDDING_DIMENSIONS))
            raise ValueError(
                f"Unknown embedding model {self.embedding_model!r}. "
                f"Add its dimension to EMBEDDING_DIMENSIONS. Known models: {known}"
            ) from exc

    @property
    def sync_database_url(self) -> str:
        """Blocking driver URL, used by ingestion and schema creation."""
        return self.database_url.replace(
            ASYNCPG_DRIVER_FRAGMENT, PSYCOPG_DRIVER_FRAGMENT
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide settings singleton."""
    return Settings()
