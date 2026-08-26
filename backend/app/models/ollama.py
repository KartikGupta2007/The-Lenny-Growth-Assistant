"""Local generation via Ollama.

Availability means two things, and both are checked: the Ollama daemon answers
on its socket, *and* the configured model has actually been pulled. Reporting
"available" for a running daemon that lacks ``llama3.1:8b`` would move the
failure to the first user question, which is the worst place for it.
"""

from __future__ import annotations

import httpx

from app.constants import (
    KIND_LOCAL,
    LABEL_OLLAMA,
    OLLAMA_DEFAULT_TAG,
    OLLAMA_MODEL_NAME_KEY,
    OLLAMA_MODELS_KEY,
    OLLAMA_TAG_SEPARATOR,
    OLLAMA_TAGS_PATH,
    PROVIDER_OLLAMA,
)
from app.http import get_http_client
from app.logging_config import get_logger
from app.models.base import ModelProvider

logger = get_logger(__name__)


class OllamaProvider(ModelProvider):
    """Generation backed by a locally running Ollama daemon."""

    id = PROVIDER_OLLAMA
    label = LABEL_OLLAMA
    kind = KIND_LOCAL

    @property
    def model_name(self) -> str:
        return self.settings.ollama_model

    async def check_availability(self) -> tuple[bool, str | None]:
        """Probe the daemon and confirm the configured model is present."""
        url = f"{self.settings.ollama_base_url}{OLLAMA_TAGS_PATH}"
        try:
            response = await get_http_client().get(
                url, timeout=self.settings.provider_probe_timeout_seconds
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
        except ValueError:  # malformed JSON from something else on the port
            logger.warning("ollama_unavailable", reason="invalid_response")
            return False, "The Ollama endpoint returned an unexpected response."

        installed = {
            model.get(OLLAMA_MODEL_NAME_KEY, "")
            for model in payload.get(OLLAMA_MODELS_KEY, [])
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
        """Match the configured model against Ollama's tag list.

        Ollama reports ``nomic-embed-text:latest`` for a model pulled as
        ``nomic-embed-text``, so an untagged configured name is compared
        against the implicit ``:latest`` tag as well.
        """
        wanted = self.model_name
        candidates = {wanted}
        if OLLAMA_TAG_SEPARATOR not in wanted:
            candidates.add(f"{wanted}{OLLAMA_TAG_SEPARATOR}{OLLAMA_DEFAULT_TAG}")
        return bool(candidates & installed)
