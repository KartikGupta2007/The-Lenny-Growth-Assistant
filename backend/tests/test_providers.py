"""Model provider selection.

The rule under test, from the product requirement: in development every
configured provider is usable; in production the *local* provider (Ollama) is
still reported so the UI can show it, but it is not selectable and the server
refuses to use it.

These tests never touch the network -- the Ollama probe is stubbed -- so they
pass on a machine with no daemon running and in CI.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.errors import ProviderUnavailableError
from app.main import create_app
from app.models.ollama import OllamaProvider
from app.models.registry import ProviderRegistry, get_provider_registry


def make_settings(**overrides: object) -> Settings:
    """Settings that ignore the developer's local .env."""
    base: dict[str, object] = {
        "_env_file": None,
        "anthropic_api_key": "test-key",
        "cors_origins": ["http://localhost:5173"],
    }
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


@pytest.fixture
def reachable_ollama(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pretend the daemon is up with the configured model pulled."""

    async def available(_self: OllamaProvider) -> tuple[bool, str | None]:
        return True, None

    monkeypatch.setattr(OllamaProvider, "check_availability", available)


def statuses_by_id(payload: dict) -> dict[str, dict]:
    return {provider["id"]: provider for provider in payload["providers"]}


class TestDevelopment:
    """APP_ENV=development -- every configured provider works."""

    async def test_all_providers_selectable(self, reachable_ollama: None) -> None:
        registry = ProviderRegistry(make_settings(app_env="development"))

        statuses = await registry.statuses()

        assert {s.id for s in statuses if s.available} == {"ollama", "anthropic"}
        assert all(s.reason is None for s in statuses)

    async def test_configured_default_is_honoured(
        self, reachable_ollama: None
    ) -> None:
        registry = ProviderRegistry(
            make_settings(app_env="development", llm_provider="ollama")
        )

        assert await registry.default_provider_id() == "ollama"


class TestProduction:
    """APP_ENV=production -- only the local provider is disabled."""

    async def test_local_provider_is_reported_but_not_available(
        self, reachable_ollama: None
    ) -> None:
        """It must still appear, so the UI can show it greyed out."""
        registry = ProviderRegistry(make_settings(app_env="production"))

        statuses = {s.id: s for s in await registry.statuses()}

        assert set(statuses) == {"ollama", "anthropic"}, "provider must not vanish"
        assert statuses["ollama"].available is False
        assert statuses["ollama"].reason  # the UI shows this next to the option

    async def test_cloud_provider_still_works(self, reachable_ollama: None) -> None:
        registry = ProviderRegistry(make_settings(app_env="production"))

        statuses = {s.id: s for s in await registry.statuses()}

        assert statuses["anthropic"].available is True
        assert statuses["anthropic"].reason is None

    async def test_default_falls_back_off_the_disabled_provider(
        self, reachable_ollama: None
    ) -> None:
        """Shipping LLM_PROVIDER=ollama to production must not brick the app."""
        registry = ProviderRegistry(
            make_settings(app_env="production", llm_provider="ollama")
        )

        assert await registry.default_provider_id() == "anthropic"

    async def test_local_provider_is_not_probed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Policy short-circuits the probe: no doomed network call per request."""
        probed = False

        async def probe(_self: OllamaProvider) -> tuple[bool, str | None]:
            nonlocal probed
            probed = True
            return True, None

        monkeypatch.setattr(OllamaProvider, "check_availability", probe)
        registry = ProviderRegistry(make_settings(app_env="production"))

        await registry.statuses()

        assert probed is False

    async def test_server_refuses_a_disabled_provider(
        self, reachable_ollama: None
    ) -> None:
        """The UI disabling the option is a courtesy; this is the control."""
        registry = ProviderRegistry(make_settings(app_env="production"))

        with pytest.raises(ProviderUnavailableError) as exc_info:
            await registry.require("ollama")

        assert exc_info.value.status_code == 503
        assert exc_info.value.context["requested"] == "ollama"

    async def test_override_re_enables_local_providers(
        self, reachable_ollama: None
    ) -> None:
        """A self-hosted production deployment that does run Ollama."""
        registry = ProviderRegistry(
            make_settings(app_env="production", enable_local_providers=True)
        )

        statuses = {s.id: s for s in await registry.statuses()}

        assert statuses["ollama"].available is True


class TestUnavailableProviders:
    """Reachability failures, as opposed to policy."""

    async def test_missing_api_key_disables_the_cloud_provider(
        self, reachable_ollama: None
    ) -> None:
        registry = ProviderRegistry(
            make_settings(app_env="development", anthropic_api_key=None)
        )

        statuses = {s.id: s for s in await registry.statuses()}

        assert statuses["anthropic"].available is False
        assert "ANTHROPIC_API_KEY" in (statuses["anthropic"].reason or "")

    async def test_blank_api_key_is_treated_as_missing(
        self, reachable_ollama: None
    ) -> None:
        registry = ProviderRegistry(
            make_settings(app_env="development", anthropic_api_key="   ")
        )

        statuses = {s.id: s for s in await registry.statuses()}

        assert statuses["anthropic"].available is False

    async def test_unreachable_ollama_reports_a_reason(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async def down(_self: OllamaProvider) -> tuple[bool, str | None]:
            return False, "Ollama is not running locally."

        monkeypatch.setattr(OllamaProvider, "check_availability", down)
        registry = ProviderRegistry(make_settings(app_env="development"))

        statuses = {s.id: s for s in await registry.statuses()}

        assert statuses["ollama"].available is False
        assert statuses["ollama"].reason == "Ollama is not running locally."

    async def test_no_provider_available_yields_no_default(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async def down(_self: OllamaProvider) -> tuple[bool, str | None]:
            return False, "not running"

        monkeypatch.setattr(OllamaProvider, "check_availability", down)
        registry = ProviderRegistry(
            make_settings(app_env="development", anthropic_api_key=None)
        )

        assert await registry.default_provider_id() is None

        with pytest.raises(ProviderUnavailableError):
            await registry.require(None)

    async def test_unknown_provider_is_rejected(
        self, reachable_ollama: None
    ) -> None:
        registry = ProviderRegistry(make_settings(app_env="development"))

        with pytest.raises(ProviderUnavailableError):
            await registry.require("gpt-9")


class TestModelTagMatching:
    """An untagged model name must match Ollama's implicit `:latest` tag."""

    def test_untagged_name_matches_latest(self) -> None:
        provider = OllamaProvider(make_settings(ollama_model="nomic-embed-text"))

        assert provider._model_installed({"nomic-embed-text:latest"}) is True

    def test_exact_tag_matches(self) -> None:
        provider = OllamaProvider(make_settings(ollama_model="llama3.1:8b"))

        assert provider._model_installed({"llama3.1:8b"}) is True

    def test_absent_model_does_not_match(self) -> None:
        provider = OllamaProvider(make_settings(ollama_model="llama3.1:8b"))

        assert provider._model_installed({"mistral:latest"}) is False


class TestProvidersEndpoint:
    """GET /api/providers -- what the model selector renders."""

    def _client(self, settings: Settings) -> TestClient:
        app = create_app(settings)
        registry = ProviderRegistry(settings)
        app.dependency_overrides[get_provider_registry] = lambda: registry
        return TestClient(app)

    def test_development_lists_both_as_available(
        self, reachable_ollama: None
    ) -> None:
        with self._client(make_settings(app_env="development")) as client:
            response = client.get("/api/providers")

        assert response.status_code == 200
        body = response.json()
        assert body["default"] == "ollama"
        assert all(p["available"] for p in body["providers"])

    def test_production_shows_ollama_disabled_with_a_reason(
        self, reachable_ollama: None
    ) -> None:
        with self._client(make_settings(app_env="production")) as client:
            response = client.get("/api/providers")

        body = response.json()
        providers = statuses_by_id(body)

        assert providers["ollama"]["available"] is False
        assert providers["ollama"]["reason"]
        assert providers["anthropic"]["available"] is True
        assert body["default"] == "anthropic"

    def test_payload_carries_what_the_ui_needs(
        self, reachable_ollama: None
    ) -> None:
        with self._client(make_settings(app_env="production")) as client:
            providers = statuses_by_id(client.get("/api/providers").json())

        assert providers["ollama"]["kind"] == "local"
        assert providers["anthropic"]["kind"] == "cloud"
        assert providers["ollama"]["label"] == "Ollama"
        assert providers["anthropic"]["label"] == "Claude"
        assert providers["anthropic"]["model"] == "claude-sonnet-5"

    def test_no_secret_is_exposed(self, reachable_ollama: None) -> None:
        """The response must never echo the credential it checked."""
        with self._client(
            make_settings(app_env="development", anthropic_api_key="super-secret")
        ) as client:
            response = client.get("/api/providers")

        assert "super-secret" not in response.text
