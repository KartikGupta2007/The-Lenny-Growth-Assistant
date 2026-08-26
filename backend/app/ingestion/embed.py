"""Embedding command: fill in the vectors ingestion left NULL.

    python -m app.ingestion.embed              # every chunk without an embedding
    python -m app.ingestion.embed --limit 32   # only the corpus's first 32 chunks

Explicitly offline, like ingestion. A user question never re-embeds the corpus;
it only embeds itself, which is the retrieval phase.

Only chunks where embedding IS NULL are read, so the command is idempotent:
rerunning it does no work, and a later ingest that adds chunks embeds just
those.

`--limit N` scopes the run to the first N chunks in corpus order, not to N
units of work. Rerunning the same limit is therefore a no-op rather than a step
through the backlog -- idempotence holds at every limit, not just the full run.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from dataclasses import dataclass

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings, get_settings
from app.db.repositories import ChunkRepository
from app.db.session import get_engine, get_sessionmaker
from app.embeddings import EmbeddingProvider, get_embedding_provider
from app.errors import EmbeddingError
from app.logging_config import configure_logging, get_logger

logger = get_logger(__name__)


@dataclass
class EmbeddingRun:
    pending: int = 0
    embedded: int = 0
    batches: int = 0

    def summary(self) -> str:
        return f"embedded={self.embedded}/{self.pending} batches={self.batches}"


async def embed_pending(
    settings: Settings,
    *,
    limit: int | None = None,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
    provider: EmbeddingProvider | None = None,
) -> EmbeddingRun:
    """Embed chunks that have no vector yet.

    `limit` scopes the run to the first N chunks in corpus order; of those,
    only the ones still missing an embedding are sent.

    Each batch is committed on its own, so a failure keeps the batches that
    succeeded and leaves the rest NULL for a rerun to finish.
    """
    factory = session_factory or get_sessionmaker()
    provider = provider or get_embedding_provider(settings)
    run = EmbeddingRun()

    async with factory() as session:
        chunks = await ChunkRepository(session).list_without_embeddings(
            within_first=limit
        )

    run.pending = len(chunks)
    if not chunks:
        logger.info("nothing_to_embed")
        return run

    batch_size = settings.embedding_batch_size
    batches = [chunks[i : i + batch_size] for i in range(0, len(chunks), batch_size)]
    logger.info(
        "embedding_started",
        chunks=len(chunks),
        batches=len(batches),
        batch_size=batch_size,
        model=settings.embedding_model,
    )

    for position, batch in enumerate(batches, start=1):
        vectors = await provider.embed([chunk.content for chunk in batch])

        # Written only after every vector in the batch validated.
        async with factory() as session:
            written = await ChunkRepository(session).set_embeddings(
                dict(zip((chunk.id for chunk in batch), vectors))
            )
            await session.commit()

        run.embedded += written
        run.batches += 1
        logger.info("batch_embedded", batch=f"{position}/{len(batches)}", chunks=written)

    logger.info("embedding_complete", **vars(run))
    return run


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Embed transcript chunks that have no embedding yet."
    )
    parser.add_argument(
        "--limit",
        type=int,
        help="only consider the first N chunks of the corpus",
    )
    args = parser.parse_args()

    settings = get_settings()
    configure_logging(settings)

    async def run() -> EmbeddingRun:
        try:
            return await embed_pending(settings, limit=args.limit)
        finally:
            await get_engine().dispose()

    # Fail loudly either way: committed batches are kept, the rest stay NULL.
    try:
        result = asyncio.run(run())
    except EmbeddingError as exc:
        print(f"Embedding failed: {exc.message}", file=sys.stderr)
        raise SystemExit(1) from exc
    except SQLAlchemyError as exc:
        print(f"Embedding failed: database error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

    print(f"Embedding complete. {result.summary()}")


if __name__ == "__main__":
    main()
