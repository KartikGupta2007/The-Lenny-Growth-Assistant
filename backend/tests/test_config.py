"""Configuration tests.

Configuration is where this application's failure modes are cheapest to catch:
a wrong embedding width silently corrupts retrieval, and a wildcard CORS
origin in production silently opens the API. Both are asserted here.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.config import Settings
from app.constants import DEFAULT_DATABASE_URL


def make(**overrides: object) -> Settings:
    """Settings that ignore the developer's local .env."""
    return Settings(_env_file=None, **overrides)  # type: ignore[arg-type]


class TestEmbeddingDimensions:
    def test_dimension_is_derived_from_model(self) -> None:
        assert make(embedding_model="nomic-embed-text").embedding_dimensions == 768
        assert make(embedding_model="mxbai-embed-large").embedding_dimensions == 1024

    def test_only_local_models_are_mapped(self) -> None:
        """Embeddings are Ollama-only; a cloud model must not silently work."""
        from app.constants import EMBEDDING_DIMENSIONS

        assert not any("text-embedding" in name for name in EMBEDDING_DIMENSIONS)

    def test_unknown_model_fails_loudly(self) -> None:
        """An unmapped model must raise, not default to a wrong width."""
        settings = make(embedding_model="some-unmapped-model")

        with pytest.raises(ValueError, match="Unknown embedding model"):
            _ = settings.embedding_dimensions


class TestListSettings:
    def test_accepts_comma_separated_string(self) -> None:
        """The form documented in .env.example."""
        settings = make(cors_origins="http://a.test, http://b.test")

        assert settings.cors_origins == ["http://a.test", "http://b.test"]

    def test_accepts_json_array(self) -> None:
        """The form a deployment console is likely to produce."""
        assert make(cors_origins='["http://a.test"]').cors_origins == ["http://a.test"]

    def test_accepts_list(self) -> None:
        assert make(cors_origins=["http://a.test"]).cors_origins == ["http://a.test"]

    def test_malformed_json_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            make(cors_origins='["http://a.test"')


class TestEnvironmentPolicy:
    """What changes between development and production."""

    def test_local_providers_enabled_outside_production(self) -> None:
        assert make(app_env="development").local_providers_enabled is True
        assert make(app_env="test").local_providers_enabled is True

    def test_local_providers_disabled_in_production(self) -> None:
        settings = make(app_env="production", cors_origins=["https://app.example"])

        assert settings.local_providers_enabled is False

    def test_local_providers_can_be_re_enabled_explicitly(self) -> None:
        """For a self-hosted production deployment that does run Ollama."""
        settings = make(
            app_env="production",
            cors_origins=["https://app.example"],
            enable_local_providers=True,
        )

        assert settings.local_providers_enabled is True

    def test_docs_are_off_in_production_by_default(self) -> None:
        assert make(app_env="development").docs_enabled is True
        assert (
            make(app_env="production", cors_origins=["https://app.example"]).docs_enabled
            is False
        )

    def test_wildcard_cors_is_rejected_in_production(self) -> None:
        with pytest.raises(ValidationError, match="explicit origins"):
            make(app_env="production", cors_origins=["*"])

    def test_wildcard_cors_is_allowed_in_development(self) -> None:
        assert make(app_env="development", cors_origins=["*"]).cors_origins == ["*"]


class TestValidation:
    def test_invalid_log_level_is_rejected(self) -> None:
        with pytest.raises(ValidationError, match="Invalid LOG_LEVEL"):
            make(log_level="VERBOSE")

    def test_log_level_is_normalised(self) -> None:
        assert make(log_level="debug").log_level == "DEBUG"

    def test_api_prefix_is_normalised(self) -> None:
        assert make(api_prefix="api/").api_prefix == "/api"
        assert make(api_prefix="/api").api_prefix == "/api"

    def test_base_urls_lose_trailing_slash(self) -> None:
        """`{base}/api/tags` would otherwise become a double slash."""
        assert make(ollama_base_url="http://x:11434/").ollama_base_url == "http://x:11434"

    def test_overlap_must_be_smaller_than_chunk(self) -> None:
        """Overlap >= chunk size would loop forever during chunking."""
        with pytest.raises(ValidationError, match="smaller than"):
            make(chunk_target_tokens=600, chunk_overlap_tokens=600)

    def test_non_positive_top_k_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            make(retrieval_top_k=0)


class TestSecrets:
    def test_api_keys_are_not_rendered_in_repr(self) -> None:
        """An accidental log of the settings object must not leak the key."""
        settings = make(anthropic_api_key="sk-secret-value")

        assert "sk-secret-value" not in repr(settings)
        assert "sk-secret-value" not in str(settings.anthropic_api_key)
        assert settings.anthropic_api_key is not None
        assert settings.anthropic_api_key.get_secret_value() == "sk-secret-value"


class TestDatabaseUrls:
    def test_sync_url_uses_blocking_driver(self) -> None:
        settings = make(database_url="postgresql+asyncpg://localhost:5432/db")

        assert settings.sync_database_url == "postgresql+psycopg://localhost:5432/db"


class TestDefaults:
    def test_local_first_defaults_require_no_cloud_credentials(self) -> None:
        """The shipped defaults must run with no API keys set."""
        settings = make()

        assert settings.llm_provider == "ollama"
        assert settings.embedding_provider == "ollama"
        assert settings.anthropic_api_key is None

    def test_embedding_provider_is_local_only(self) -> None:
        """A non-Ollama embedding provider must be rejected, not ignored."""
        with pytest.raises(ValidationError):
            make(embedding_provider="openai")


class TestEmptyEnvValues:
    """`.env.example` ships placeholder keys with no value."""

    def test_empty_database_url_falls_back_to_the_default(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`cp .env.example .env` must not produce an invalid DSN."""
        monkeypatch.setenv("DATABASE_URL", "")

        assert make().database_url == DEFAULT_DATABASE_URL

    def test_empty_api_key_is_none_not_blank(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("ANTHROPIC_API_KEY", "")

        assert make().anthropic_api_key is None
