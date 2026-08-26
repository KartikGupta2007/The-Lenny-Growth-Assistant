"""Find the transcript chunks that could answer a question.

    query -> query embedding -> pgvector search -> threshold -> top-k + provenance

Retrieval only. Nothing here writes to the database or generates an answer.

Document embeddings are made offline by `python -m app.ingestion.embed`; only
the query is embedded here, so a question costs one small embedding call rather
than re-embedding the corpus.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.db.repositories import ChunkRepository
from app.embeddings import EmbeddingProvider, get_embedding_provider
from app.logging_config import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class RetrievedChunk:
    """One chunk, with everything a citation needs."""

    chunk_id: uuid.UUID
    document_id: uuid.UUID
    content: str
    chunk_index: int
    distance: float
    title: str
    guest: str | None
    source_url: str | None
    source_path: str


@dataclass(frozen=True)
class RetrievalResult:
    query: str
    chunks: list[RetrievedChunk]
    # False when too little relevant material was found to answer safely. The
    # caller must say so rather than answering from whatever came back.
    sufficient: bool


async def retrieve(
    session: AsyncSession,
    query: str,
    *,
    settings: Settings | None = None,
    provider: EmbeddingProvider | None = None,
) -> RetrievalResult:
    """Retrieve chunks relevant to `query`.

    Chunks beyond RETRIEVAL_MAX_DISTANCE are dropped, and if fewer than
    RETRIEVAL_MIN_CHUNKS survive the result is marked insufficient -- an
    unrelated question should produce no evidence, not the nearest vector.
    """
    settings = settings or get_settings()
    query = query.strip()
    if not query:
        return RetrievalResult(query=query, chunks=[], sufficient=False)

    provider = provider or get_embedding_provider(settings)
    # The provider validates the width before we hand it to pgvector.
    [query_embedding] = await provider.embed([query])

    rows = await ChunkRepository(session).search_similar(
        query_embedding,
        top_k=settings.retrieval_top_k,
        max_distance=settings.retrieval_max_distance,
    )
    chunks = [
        RetrievedChunk(
            chunk_id=row.chunk_id,
            document_id=row.document_id,
            content=row.content,
            chunk_index=row.chunk_index,
            distance=float(row.distance),
            title=row.title,
            guest=row.guest,
            source_url=row.source_url,
            source_path=row.source_path,
        )
        for row in rows
    ]

    sufficient = len(chunks) >= settings.retrieval_min_chunks
    logger.info(
        "retrieval_completed",
        chunks=len(chunks),
        sufficient=sufficient,
        best_distance=round(chunks[0].distance, 4) if chunks else None,
    )
    if not sufficient:
        logger.info("insufficient_evidence", chunks=len(chunks))

    return RetrievalResult(query=query, chunks=chunks, sufficient=sufficient)
