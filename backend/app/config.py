"""Environment-driven configuration.

Everything tunable is declared here so no other module reads os.environ.
Defaults come from constants.py. Secrets are SecretStr so an accidental log of
the settings object cannot leak them.

The .env path is resolved from the backend/ package rather than the working
directory, so `uvicorn app.main:app` behaves the same from either.
"""

from __future__ import annotations

import json
import logging
from functools import lru_cache
from typing import Annotated

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

from app.constants import (
    API_PREFIX,
    APP_VERSION,
    BACKEND_DIR,
    DEFAULT_ANTHROPIC_MODEL,
    DEFAULT_ANTHROPIC_TIMEOUT_SECONDS,
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
    EmbeddingProviderId,
    Environment,
    LLMProviderId,
)


class Settings(BaseSettings):
    """Backend settings, loaded from the environment and backend/.env."""

    model_config = SettingsConfigDict(
        env_file=BACKEND_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
        # .env.example ships placeholder keys with no value; an empty value
        # must mean "unset" rather than override the default with "".
        env_ignore_empty=True,
    )

    # ---- Application ----
    app_env: Environment = "development"
    app_version: str = APP_VERSION
    log_level: str = "INFO"
    api_prefix: str = API_PREFIX

    # NoDecode stops pydantic-settings JSON-decoding the raw value before
    # validation, so the comma-separated form in .env.example parses.
    cors_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: list(DEFAULT_CORS_ORIGINS)
    )
    # "*" is fine behind a proxy that already validates the Host header.
    allowed_hosts: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["*"]
    )
    # None means "on everywhere except production".
    enable_docs: bool | None = None

    # ---- Database ----
    # No username: psycopg falls back to the OS user, which is how Homebrew
    # provisions PostgreSQL. Managed instances need an explicit user:password@.
    database_url: str = DEFAULT_DATABASE_URL
    database_probe_timeout_seconds: float = Field(
        default=DEFAULT_DATABASE_PROBE_TIMEOUT_SECONDS, gt=0
    )

    # ---- LLM providers ----
    llm_provider: LLMProviderId = DEFAULT_LLM_PROVIDER

    # Local providers are unavailable in production by default: the hosted API
    # has no Ollama daemon. Set explicitly for a self-hosted deployment.
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

    provider_probe_timeout_seconds: float = Field(
        default=DEFAULT_PROVIDER_PROBE_TIMEOUT_SECONDS, gt=0
    )
    provider_status_ttl_seconds: float = Field(
        default=DEFAULT_PROVIDER_STATUS_TTL_SECONDS, ge=0
    )

    # ---- Embeddings ----
    # Always Ollama, independent of llm_provider, so ingestion needs no key.
    embedding_provider: EmbeddingProviderId = DEFAULT_EMBEDDING_PROVIDER
    embedding_model: str = DEFAULT_EMBEDDING_MODEL
    embedding_batch_size: int = Field(default=DEFAULT_EMBEDDING_BATCH_SIZE, gt=0)
    embedding_timeout_seconds: float = Field(
        default=DEFAULT_EMBEDDING_TIMEOUT_SECONDS, gt=0
    )

    # ---- Ingestion ----
    transcript_repo: str = DEFAULT_TRANSCRIPT_REPO
    transcript_repo_ref: str = DEFAULT_TRANSCRIPT_REPO_REF
    transcript_cache_dir: str = DEFAULT_TRANSCRIPT_CACHE_DIR
    chunk_target_tokens: int = Field(default=DEFAULT_CHUNK_TARGET_TOKENS, gt=0)
    chunk_overlap_tokens: int = Field(default=DEFAULT_CHUNK_OVERLAP_TOKENS, ge=0)

    # ---- Retrieval ----
    retrieval_top_k: int = Field(default=DEFAULT_RETRIEVAL_TOP_K, gt=0)
    retrieval_max_distance: float = Field(
        default=DEFAULT_RETRIEVAL_MAX_DISTANCE, gt=0, le=2.0
    )
    retrieval_min_chunks: int = Field(default=DEFAULT_RETRIEVAL_MIN_CHUNKS, gt=0)

    # ---- Outbound HTTP ----
    http_max_connections: int = Field(default=DEFAULT_HTTP_MAX_CONNECTIONS, gt=0)

    @field_validator("cors_origins", "allowed_hosts", mode="before")
    @classmethod
    def _split_list(cls, value: object) -> object:
        """Accept a comma-separated string, a JSON array, or a list."""
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
        """Reject a misspelled level instead of falling back to INFO."""
        level = value.upper()
        if not isinstance(logging.getLevelName(level), int):
            raise ValueError(f"Invalid LOG_LEVEL {value!r}")
        return level

    @field_validator("api_prefix")
    @classmethod
    def _normalise_prefix(cls, value: str) -> str:
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
        if self.is_production and "*" in self.cors_origins:
            raise ValueError(
                "CORS_ORIGINS must list explicit origins in production; "
                "'*' would let any site call the API."
            )
        return self

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @property
    def docs_enabled(self) -> bool:
        """Whether /docs, /redoc and /openapi.json are served."""
        if self.enable_docs is not None:
            return self.enable_docs
        return not self.is_production

    @property
    def local_providers_enabled(self) -> bool:
        """Whether a locally hosted provider may be selected.

        Policy, not reachability: in production Ollama is still reported to the
        UI, but marked unselectable rather than silently dropped.
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
                f"Add its dimension to EMBEDDING_DIMENSIONS. Known: {known}"
            ) from exc

    @property
    def sqlalchemy_url(self) -> str:
        """DSN pinned to psycopg 3, used by both the async and sync engines.

        A bare postgresql:// DSN -- what Neon's console hands you -- makes
        SQLAlchemy reach for psycopg2, which this project does not install.
        """
        url = self.database_url
        if "+asyncpg" in url:
            return url.replace("+asyncpg", "+psycopg")
        if url.startswith("postgresql://"):
            return url.replace("postgresql://", "postgresql+psycopg://", 1)
        return url


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide settings singleton."""
    return Settings()
