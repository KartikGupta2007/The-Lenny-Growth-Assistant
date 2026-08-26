"""Cloud generation and availability via the Anthropic API."""

from __future__ import annotations

import anthropic

from app.constants import PROVIDER_ANTHROPIC
from app.errors import ModelError, ModelTimeoutError, ProviderUnavailableError
from app.models.base import Message, ModelProvider

# Enough for a Ship 30 essay (~1,250 words) with room to spare.
MAX_OUTPUT_TOKENS = 4096


def build_client(api_key: str, timeout: float) -> anthropic.AsyncAnthropic:
    """Construct the SDK client.

    A seam for tests, which swap in a mock transport. The SDK ships its own
    HTTP stack (httpx2), so it cannot share the application's pooled httpx
    client; a client per request costs one handshake against a call that takes
    seconds, which is not worth extra lifecycle machinery to avoid.
    """
    return anthropic.AsyncAnthropic(api_key=api_key, timeout=timeout)


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
        surfaces as a ProviderUnavailableError at generation time instead.
        """
        if self._api_key() is None:
            return False, (
                "No Anthropic API key is configured. Set ANTHROPIC_API_KEY to "
                "enable this model."
            )
        return True, None

    def _api_key(self) -> str | None:
        key = self.settings.anthropic_api_key
        if key is None or not key.get_secret_value().strip():
            return None
        return key.get_secret_value().strip()

    async def generate(self, system: str, messages: list[Message]) -> str:
        key = self._api_key()
        if key is None:
            raise ProviderUnavailableError(
                "No Anthropic API key is configured.", requested=self.id
            )

        client = build_client(key, self.settings.anthropic_timeout_seconds)
        try:
            response = await client.messages.create(
                model=self.model_name,
                max_tokens=MAX_OUTPUT_TOKENS,
                system=system,
                messages=[{"role": m.role, "content": m.content} for m in messages],
            )
        except anthropic.APITimeoutError as exc:
            raise ModelTimeoutError(
                f"{self.label} did not respond within "
                f"{self.settings.anthropic_timeout_seconds:g}s."
            ) from exc
        except anthropic.AuthenticationError as exc:
            # The key is present but rejected. Never echo it.
            raise ProviderUnavailableError(
                f"{self.label} rejected the configured API key.", requested=self.id
            ) from exc
        except anthropic.APIError as exc:
            raise ModelError(f"{self.label} could not generate a response.") from exc
        finally:
            await client.close()

        answer = "".join(
            block.text
            for block in response.content
            if getattr(block, "type", "") == "text"
        ).strip()
        if not answer:
            raise ModelError(f"{self.label} returned an empty response.")
        return answer
