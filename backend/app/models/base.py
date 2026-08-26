"""Model provider abstraction.

Application code depends on :class:`ModelProvider`, never on a vendor SDK, so
switching between local and cloud generation is a configuration change rather
than a code change (architecture.md section 20).

A provider answers two separate questions, which must not be conflated:

``is_enabled``
    *Policy*: may this provider be used in this environment at all? Local
    providers are disabled in production regardless of reachability.
``check_availability``
    *Reality*: is the provider actually reachable and correctly configured
    right now?

The UI needs both, because a provider that is disabled by policy is still
shown -- greyed out, with the reason -- rather than silently omitted.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import ClassVar

from pydantic import BaseModel

from app.config import Settings
from app.constants import KIND_LOCAL, LLMProviderId, ProviderKind


class ProviderStatus(BaseModel):
    """Selectability of one provider, as reported to the frontend.

    ``available`` is the single flag the UI switches on: an entry is rendered
    as a disabled option with ``reason`` shown when it is ``False``.
    """

    id: LLMProviderId
    label: str
    kind: ProviderKind
    model: str
    available: bool
    # User-facing explanation, present only when ``available`` is False.
    reason: str | None = None


class ModelProvider(ABC):
    """Base class for a generation backend."""

    id: ClassVar[LLMProviderId]
    label: ClassVar[str]
    kind: ClassVar[ProviderKind]

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    @property
    @abstractmethod
    def model_name(self) -> str:
        """Concrete model this provider would generate with."""

    @property
    def is_enabled(self) -> bool:
        """Whether environment policy permits this provider.

        Local providers are gated on ``Settings.local_providers_enabled``;
        cloud providers are always permitted by policy and gated only on
        configuration.
        """
        if self.kind == KIND_LOCAL:
            return self.settings.local_providers_enabled
        return True

    @property
    def policy_reason(self) -> str:
        """Why a policy-disabled provider is unavailable."""
        return (
            f"{self.label} runs on the machine hosting the API and is not "
            "available in this environment. Use a cloud model instead."
        )

    @abstractmethod
    async def check_availability(self) -> tuple[bool, str | None]:
        """Probe the provider.

        Returns:
            ``(available, reason)`` where ``reason`` is a user-facing
            explanation and is ``None`` when available. Implementations must
            not raise: an unreachable dependency is a normal outcome here.
        """

    async def status(self) -> ProviderStatus:
        """Resolve policy, then reality, into a single reported status."""
        if not self.is_enabled:
            # Skip the probe entirely: in production there is no Ollama to
            # reach, and a doomed network call per request would be waste.
            return ProviderStatus(
                id=self.id,
                label=self.label,
                kind=self.kind,
                model=self.model_name,
                available=False,
                reason=self.policy_reason,
            )

        available, reason = await self.check_availability()
        return ProviderStatus(
            id=self.id,
            label=self.label,
            kind=self.kind,
            model=self.model_name,
            available=available,
            reason=None if available else reason,
        )
