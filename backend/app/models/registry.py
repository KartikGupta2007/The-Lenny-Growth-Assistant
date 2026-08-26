"""Provider registry: availability, defaults, and server-side enforcement.

The frontend disables an unselectable option, but that is a courtesy, not a
control -- `require` re-checks on every request, so a hand-crafted call cannot
select a provider the environment has disabled.
"""

from __future__ import annotations

import asyncio
import time
from functools import lru_cache

from app.config import Settings, get_settings
from app.constants import LLMProviderId
from app.errors import ProviderUnavailableError
from app.logging_config import get_logger
from app.models.base import ModelProvider, ProviderStatus
from app.models.cloud import CloudModelProvider
from app.models.ollama import OllamaProvider

logger = get_logger(__name__)

# Declaration order is display order in the UI: local first.
PROVIDER_TYPES: tuple[type[ModelProvider], ...] = (OllamaProvider, CloudModelProvider)


class ProviderRegistry:
    """Holds provider instances and their cached availability."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._providers: dict[str, ModelProvider] = {
            provider_type.id: provider_type(settings)
            for provider_type in PROVIDER_TYPES
        }
        self._cache: list[ProviderStatus] | None = None
        self._cached_at = 0.0
        self._lock = asyncio.Lock()

    def get(self, provider_id: str) -> ModelProvider | None:
        return self._providers.get(provider_id)

    async def statuses(self) -> list[ProviderStatus]:
        """Status of every known provider, cached briefly.

        Every provider is always returned, including disabled ones, so the UI
        can grey an option out instead of making it disappear.

        Cached because a page load plus a message send would otherwise each
        probe Ollama, and a dead daemon would cost the timeout every time.
        """
        async with self._lock:
            age = time.monotonic() - self._cached_at
            if self._cache is None or age >= self.settings.provider_status_ttl_seconds:
                self._cache = list(
                    await asyncio.gather(
                        *(provider.status() for provider in self._providers.values())
                    )
                )
                self._cached_at = time.monotonic()
                logger.info(
                    "provider_status_refreshed",
                    available=[s.id for s in self._cache if s.available],
                    unavailable=[s.id for s in self._cache if not s.available],
                )
            return self._cache

    async def default_provider_id(self) -> LLMProviderId | None:
        """The provider a new conversation should use.

        Falls back to the first available one, so shipping LLM_PROVIDER=ollama
        to production still opens on a working model. None if nothing works.
        """
        statuses = await self.statuses()
        by_id = {status.id: status for status in statuses}

        configured = by_id.get(self.settings.llm_provider)
        if configured is not None and configured.available:
            return configured.id

        for status in statuses:
            if status.available:
                logger.info(
                    "provider_default_fallback",
                    configured=self.settings.llm_provider,
                    selected=status.id,
                )
                return status.id

        logger.error("no_provider_available")
        return None

    async def require(self, provider_id: str | None) -> ModelProvider:
        """Return a usable provider or raise. None means "use the default"."""
        if provider_id is None:
            resolved = await self.default_provider_id()
            if resolved is None:
                raise ProviderUnavailableError(
                    "No model provider is currently available."
                )
            provider_id = resolved

        provider = self.get(provider_id)
        if provider is None:
            raise ProviderUnavailableError(
                "The requested model is not recognised.", requested=provider_id
            )

        status = next(
            (s for s in await self.statuses() if s.id == provider_id), None
        )
        if status is None or not status.available:
            raise ProviderUnavailableError(
                (status.reason if status else None)
                or "The selected model is currently unavailable.",
                requested=provider_id,
            )

        return provider


@lru_cache(maxsize=1)
def get_provider_registry() -> ProviderRegistry:
    return ProviderRegistry(get_settings())
