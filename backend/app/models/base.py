"""Model provider abstraction.

Application code depends on ModelProvider, never on a vendor SDK, so switching
between local and cloud generation is a configuration change.

A provider answers two separate questions:

    is_enabled          -- may this provider be used in this environment?
    check_availability  -- is it reachable and configured right now?

The UI needs both: a provider disabled by policy is still shown, greyed out
with the reason, rather than silently omitted.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import ClassVar

from pydantic import BaseModel

from app.config import Settings
from app.constants import LLMProviderId, MessageRole, ProviderKind


class Message(BaseModel):
    """One conversation turn as sent to a provider."""

    role: MessageRole
    content: str


class ProviderStatus(BaseModel):
    """Selectability of one provider, as reported to the frontend."""

    id: LLMProviderId
    label: str
    kind: ProviderKind
    model: str
    available: bool
    # User-facing explanation, present only when available is False.
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
        """The model this provider would generate with."""

    @property
    def is_enabled(self) -> bool:
        """Whether environment policy permits this provider."""
        if self.kind == "local":
            return self.settings.local_providers_enabled
        return True

    @abstractmethod
    async def check_availability(self) -> tuple[bool, str | None]:
        """Probe the provider.

        Returns (available, reason). Must not raise: an unreachable dependency
        is a normal outcome here.
        """

    @abstractmethod
    async def generate(self, system: str, messages: list[Message]) -> str:
        """Generate a reply to `messages` under the `system` instruction.

        Raises ModelTimeoutError, ModelError or ProviderUnavailableError -- the
        caller distinguishes "try again" from "pick another model".
        """

    async def status(self) -> ProviderStatus:
        """Resolve policy, then reachability, into a reported status."""
        if not self.is_enabled:
            # Skip the probe: in production there is no daemon to reach.
            return ProviderStatus(
                id=self.id,
                label=self.label,
                kind=self.kind,
                model=self.model_name,
                available=False,
                reason=(
                    f"{self.label} runs on the machine hosting the API and is "
                    "not available in this environment. Use a cloud model."
                ),
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
