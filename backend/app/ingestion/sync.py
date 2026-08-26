"""Ingestion command: sync the transcript repository into the database.

    python -m app.ingestion.sync                # whole corpus
    python -m app.ingestion.sync --limit 10     # first 10 transcripts
    python -m app.ingestion.sync --force-sync   # re-download the repository

Explicitly offline. Nothing here runs during a user request. Embeddings are a
separate phase; chunks are written with a NULL embedding.
"""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings, get_settings
from app.db import models
from app.db.repositories import ChunkRepository, DocumentRepository
from app.db.session import get_engine, get_sessionmaker
from app.ingestion.chunker import chunk_transcript
from app.ingestion.loader import discover_transcripts, sync_repository
from app.ingestion.parser import ParsedTranscript, TranscriptError, parse_transcript
from app.logging_config import configure_logging, get_logger

logger = get_logger(__name__)


@dataclass
class IngestionResult:
    created: int = 0
    updated: int = 0
    skipped: int = 0
    removed: int = 0
    failed: int = 0
    chunks_written: int = 0

    def summary(self) -> str:
        return (
            f"created={self.created} updated={self.updated} "
            f"skipped={self.skipped} removed={self.removed} "
            f"failed={self.failed} chunks={self.chunks_written}"
        )


async def ingest(
    settings: Settings,
    *,
    limit: int | None = None,
    force_sync: bool = False,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
) -> IngestionResult:
    """Sync, parse, chunk and store the corpus.

    `session_factory` defaults to the application's; tests pass their own.
    """
    root = sync_repository(settings, force=force_sync)
    paths = discover_transcripts(root)
    logger.info("transcripts_found", count=len(paths))

    if limit is not None:
        paths = paths[:limit]

    result = IngestionResult()
    factory = session_factory or get_sessionmaker()

    for position, path in enumerate(paths, start=1):
        source_path = path.relative_to(root).as_posix()
        try:
            parsed = parse_transcript(path, source_path)
        except TranscriptError as exc:
            result.failed += 1
            logger.warning("transcript_unreadable", source_path=source_path, error=str(exc))
            continue

        # One transaction per transcript, so an interrupted run keeps the work
        # it finished and a rerun resumes from there.
        async with factory() as session:
            outcome, chunk_count = await _store(session, settings, parsed)
            await session.commit()

        setattr(result, outcome, getattr(result, outcome) + 1)
        result.chunks_written += chunk_count
        logger.info(
            "transcript_processed",
            position=f"{position}/{len(paths)}",
            source_path=source_path,
            outcome=outcome,
            chunks=chunk_count,
        )

    # Pruning is skipped under --limit: the discovered set is truncated, so
    # every transcript beyond the limit would look like it had been removed.
    if limit is None:
        async with factory() as session:
            result.removed = await _prune(
                session, {p.relative_to(root).as_posix() for p in paths}
            )
            await session.commit()
    elif result.created or result.updated:
        logger.info("prune_skipped", reason="limit")

    logger.info("ingestion_complete", **vars(result))
    return result


async def _store(
    session: AsyncSession, settings: Settings, parsed: ParsedTranscript
) -> tuple[str, int]:
    """Upsert one document and rebuild its chunks if the content changed."""
    documents = DocumentRepository(session)
    document, changed = await documents.upsert(
        source_path=parsed.source_path,
        title=parsed.title,
        content_hash=parsed.content_hash,
        source_url=parsed.source_url,
        guest=parsed.guest,
        publish_date=parsed.publish_date,
    )
    was_new = document.last_ingested_at is None

    chunks = ChunkRepository(session)
    if not changed and await chunks.count_by_document(document.id):
        return "skipped", 0

    # Boundaries move when the text changes, so old chunk indexes cannot be
    # reused -- replace the set rather than updating in place.
    await chunks.delete_by_document(document.id)
    written = await chunks.bulk_insert(
        [
            models.Chunk(
                document_id=document.id,
                chunk_index=chunk.index,
                content=chunk.text,
                content_hash=chunk.content_hash,
                chunk_metadata={"word_count": chunk.word_count},
            )
            for chunk in chunk_transcript(
                parsed.text,
                target_words=settings.chunk_target_tokens,
                overlap_words=settings.chunk_overlap_tokens,
            )
        ]
    )
    await documents.mark_ingested(document.id)
    return ("created" if was_new else "updated"), written


async def _prune(session: AsyncSession, present: set[str]) -> int:
    """Delete documents whose transcript is gone from the repository.

    Their chunks go with them: the foreign key cascades.
    """
    stored = (await session.execute(select(models.Document))).scalars().all()
    stale = [document for document in stored if document.source_path not in present]
    for document in stale:
        logger.info("document_removed", source_path=document.source_path)
        await session.delete(document)
    return len(stale)


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest Lenny's Podcast transcripts.")
    parser.add_argument(
        "--limit", type=int, help="only process the first N transcripts"
    )
    parser.add_argument(
        "--force-sync", action="store_true", help="re-download the repository"
    )
    args = parser.parse_args()

    settings = get_settings()
    configure_logging(settings)

    async def run() -> IngestionResult:
        try:
            return await ingest(settings, limit=args.limit, force_sync=args.force_sync)
        finally:
            await get_engine().dispose()

    result = asyncio.run(run())
    print(f"Ingestion complete. {result.summary()}")


if __name__ == "__main__":
    main()
