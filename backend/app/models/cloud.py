"""Cloud generation via the Anthropic API."""

from __future__ import annotations

from app.constants import PROVIDER_ANTHROPIC
from app.models.base import ModelProvider


class CloudModelProvider(ModelProvider):
    """Generation backed by the Anthropic API."""

    id = PROVIDER_ANTHROPIC
    label = "Claude"
    kind = "cloud"

    @property
    def model_name(self) -> str:
        return self.settings.anthropic_model

    async def check_availability(self) -> tuple[bool, str | None]:
        """Report whether a credential is configured.

        Deliberately offline: the UI calls GET /api/providers on load, and a
        vendor round-trip there would add latency and cost. A rejected key
        surfaces as a ModelError at generation time instead.
        """
        key = self.settings.anthropic_api_key
        if key is None or not key.get_secret_value().strip():
            return False, (
                "No Anthropic API key is configured. Set ANTHROPIC_API_KEY to "
                "enable this model."
            )
        return True, None
