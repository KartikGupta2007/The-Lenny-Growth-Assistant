"""Embedding provider.

One provider today -- Ollama, running locally, so embedding the corpus needs no
API key and costs nothing. The abstraction exists because the architecture
keeps the embedding provider replaceable, not because there is a second one.

The expected vector width comes from Settings.embedding_dimensions, which is
derived from EMBEDDING_MODEL. A provider returning a different width would
silently corrupt retrieval, so it is checked before anything is stored.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence

import httpx

from app.config import Settings, get_settings
from app.errors import EmbeddingError
from app.http import get_http_client
from app.logging_config import get_logger

logger = get_logger(__name__)


class EmbeddingProvider(ABC):
    """Turns text into vectors."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    @property
    def dimensions(self) -> int:
        return self.settings.embedding_dimensions

    @abstractmethod
    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        """Embed every text in one request, in order.

        Raises EmbeddingError if the provider is unreachable, times out, or
        returns vectors of the wrong shape.
        """


class OllamaEmbeddingProvider(EmbeddingProvider):
    """Embeddings from a local Ollama daemon."""

    @property
    def model(self) -> str:
        return self.settings.embedding_model

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []

        url = f"{self.settings.ollama_base_url}/api/embed"
        try:
            response = await get_http_client().post(
                url,
                json={"model": self.model, "input": list(texts)},
                timeout=self.settings.embedding_timeout_seconds,
            )
            response.raise_for_status()
            payload = response.json()
        except httpx.TimeoutException as exc:
            raise EmbeddingError(
                f"Ollama did not respond within "
                f"{self.settings.embedding_timeout_seconds:g}s. "
                "Try a smaller EMBEDDING_BATCH_SIZE."
            ) from exc
        except httpx.HTTPStatusError as exc:
            detail = _model_missing_hint(exc, self.model)
            raise EmbeddingError(f"Ollama rejected the request: {detail}") from exc
        except httpx.HTTPError as exc:
            raise EmbeddingError(
                "Ollama is not reachable. Start it with "
                "`brew services start ollama`."
            ) from exc
        except ValueError as exc:
            raise EmbeddingError("Ollama returned a malformed response.") from exc

        return self._validate(payload.get("embeddings"), len(texts))

    def _validate(self, vectors: object, expected_count: int) -> list[list[float]]:
        """Reject anything that is not exactly the vectors we asked for."""
        if not isinstance(vectors, list) or len(vectors) != expected_count:
            raise EmbeddingError(
                f"Ollama returned {len(vectors) if isinstance(vectors, list) else 0} "
                f"embeddings for {expected_count} inputs."
            )

        for position, vector in enumerate(vectors):
            if not isinstance(vector, list) or len(vector) != self.dimensions:
                actual = len(vector) if isinstance(vector, list) else "not a vector"
                raise EmbeddingError(
                    f"{self.model} returned {actual} dimensions at position "
                    f"{position}; the schema expects {self.dimensions}. "
                    "Check EMBEDDING_MODEL against the ingested corpus."
                )

        return [[float(value) for value in vector] for vector in vectors]


def _model_missing_hint(exc: httpx.HTTPStatusError, model: str) -> str:
    """Turn Ollama's 404 for an unpulled model into something actionable."""
    if exc.response.status_code == 404:
        return f"model {model} is not installed. Pull it with `ollama pull {model}`."
    return f"HTTP {exc.response.status_code}."


def get_embedding_provider(settings: Settings | None = None) -> EmbeddingProvider:
    return OllamaEmbeddingProvider(settings or get_settings())
