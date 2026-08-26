"""Cloud generation via the Anthropic API.

Availability is treated as "a credential is configured". The probe is
deliberately offline: a live round-trip to the vendor on every
``GET /api/providers`` call would add latency and cost to a request the UI
makes on load, and a valid key that is momentarily rate-limited is not the
same failure as a missing key. Credential rejection surfaces as a
:class:`~app.errors.ModelError` at generation time instead.
"""

from __future__ import annotations

from app.constants import KIND_CLOUD, LABEL_ANTHROPIC, PROVIDER_ANTHROPIC
from app.models.base import ModelProvider


class CloudModelProvider(ModelProvider):
    """Generation backed by the Anthropic API."""

    id = PROVIDER_ANTHROPIC
    label = LABEL_ANTHROPIC
    kind = KIND_CLOUD

    @property
    def model_name(self) -> str:
        return self.settings.anthropic_model

    async def check_availability(self) -> tuple[bool, str | None]:
        """Report whether a credential is configured."""
        key = self.settings.anthropic_api_key
        if key is None or not key.get_secret_value().strip():
            return False, (
                "No Anthropic API key is configured. Set ANTHROPIC_API_KEY to "
                "enable this model."
            )
        return True, None
