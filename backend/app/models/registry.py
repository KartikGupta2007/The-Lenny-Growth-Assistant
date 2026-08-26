"""Provider registry: availability, defaults and server-side enforcement.

The registry is the single place that answers "which model may this request
use?". The frontend disables an unselectable option, but that is a courtesy,
not a control: :meth:`ProviderRegistry.require` re-checks on every request so
a hand-crafted call cannot select a provider the environment has disabled.

Probe results are cached for ``PROVIDER_STATUS_TTL_SECONDS``. Without it, a
page load plus a message send would each pay a network round-trip to Ollama,
and a dead daemon would cost the probe timeout every time.
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

# Declaration order is display order in the UI: local first, matching
# design.md section 10, where the local demo is the primary path.
PROVIDER_TYPES: tuple[type[ModelProvider], ...] = (OllamaProvider, CloudModelProvider)


class ProviderRegistry:
    """Holds provider instances and their cached availability."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._providers: dict[LLMProviderId, ModelProvider] = {
            provider_type.id: provider_type(settings)
            for provider_type in PROVIDER_TYPES
        }
        self._cache: list[ProviderStatus] | None = None
        self._cached_at = 0.0
        self._lock = asyncio.Lock()

    def get(self, provider_id: str) -> ModelProvider | None:
        """Return a provider by id, or ``None`` if the id is unknown."""
        return self._providers.get(provider_id)  # type: ignore[arg-type]

    async def statuses(self, *, refresh: bool = False) -> list[ProviderStatus]:
        """Return the status of every known provider, newest-first cached.

        Every provider is always returned, including ones that are disabled,
        so the UI can render them greyed out with an explanation rather than
        making an option disappear between environments.
        """
        if not refresh and self._is_cache_fresh():
            return self._cache or []

        async with self._lock:
            # Another coroutine may have refreshed while we waited.
            if not refresh and self._is_cache_fresh():
                return self._cache or []

            statuses = await asyncio.gather(
                *(provider.status() for provider in self._providers.values())
            )
            self._cache = list(statuses)
            self._cached_at = time.monotonic()

        logger.info(
            "provider_status_refreshed",
            available=[s.id for s in self._cache if s.available],
            unavailable=[s.id for s in self._cache if not s.available],
        )
        return self._cache

    def _is_cache_fresh(self) -> bool:
        if self._cache is None:
            return False
        age = time.monotonic() - self._cached_at
        return age < self.settings.provider_status_ttl_seconds

    async def default_provider_id(self) -> LLMProviderId | None:
        """Resolve the provider a new conversation should use.

        Prefers the configured ``LLM_PROVIDER`` and falls back to the first
        available provider, so a deployment that ships the local default into
        production still opens on a working model instead of a dead option.
        Returns ``None`` when nothing is available at all.
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
        """Return a usable provider or raise.

        This is the enforcement point for generation requests. ``None`` means
        "use the default". An unknown, policy-disabled or unreachable provider
        raises :class:`ProviderUnavailableError` carrying the user-facing
        reason, so the client sees why rather than a bare 503.
        """
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
                "The requested model is not recognised.",
                requested=provider_id,
            )

        status = next(
            (s for s in await self.statuses() if s.id == provider_id),
            None,
        )
        if status is None or not status.available:
            reason = status.reason if status else None
            raise ProviderUnavailableError(
                reason or "The selected model is currently unavailable.",
                requested=provider_id,
            )

        return provider


@lru_cache(maxsize=1)
def get_provider_registry() -> ProviderRegistry:
    """Return the process-wide registry."""
    return ProviderRegistry(get_settings())
