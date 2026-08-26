"""Local generation via Ollama."""

from __future__ import annotations

import httpx

from app.constants import PROVIDER_OLLAMA
from app.http import get_http_client
from app.logging_config import get_logger
from app.models.base import ModelProvider

logger = get_logger(__name__)


class OllamaProvider(ModelProvider):
    """Generation backed by a locally running Ollama daemon."""

    id = PROVIDER_OLLAMA
    label = "Ollama"
    kind = "local"

    @property
    def model_name(self) -> str:
        return self.settings.ollama_model

    async def check_availability(self) -> tuple[bool, str | None]:
        """Check the daemon is up and the configured model is pulled.

        Both matter: a running daemon without the model would move the failure
        to the user's first question.
        """
        try:
            response = await get_http_client().get(
                f"{self.settings.ollama_base_url}/api/tags",
                timeout=self.settings.provider_probe_timeout_seconds,
            )
            response.raise_for_status()
            payload = response.json()
        except httpx.TimeoutException:
            logger.warning("ollama_unavailable", reason="timeout")
            return False, "Ollama did not respond in time. Is it running?"
        except httpx.HTTPError as exc:
            logger.warning("ollama_unavailable", reason="unreachable", error=str(exc))
            return False, (
                "Ollama is not running locally. Start it with "
                "`brew services start ollama`."
            )
        except ValueError:
            logger.warning("ollama_unavailable", reason="invalid_response")
            return False, "The Ollama endpoint returned an unexpected response."

        installed = {
            model.get("name", "")
            for model in payload.get("models", [])
            if isinstance(model, dict)
        }
        if not self._model_installed(installed):
            logger.warning(
                "ollama_unavailable", reason="model_missing", model=self.model_name
            )
            return False, (
                f"The model {self.model_name} is not installed. "
                f"Pull it with `ollama pull {self.model_name}`."
            )

        return True, None

    def _model_installed(self, installed: set[str]) -> bool:
        """Ollama reports `name:latest` for a model pulled untagged."""
        wanted = self.model_name
        candidates = {wanted}
        if ":" not in wanted:
            candidates.add(f"{wanted}:latest")
        return bool(candidates & installed)
