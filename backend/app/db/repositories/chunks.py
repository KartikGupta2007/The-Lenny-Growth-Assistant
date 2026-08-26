"""Data access for transcript chunks.

Storage only. Splitting transcripts, computing embeddings and vector search
are later phases.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence

from sqlalchemy import Row, delete, func, select, update

from app.db import models
from app.db.repositories.base import BaseRepository


class ChunkRepository(BaseRepository):
    async def bulk_insert(self, chunks: Sequence[models.Chunk]) -> int:
        """SQLAlchemy batches same-mapper inserts, so a whole transcript's
        chunks cost a handful of round-trips rather than one each."""
        if not chunks:
            return 0
        self.session.add_all(chunks)
        await self.session.flush()
        return len(chunks)

    async def list_by_document(self, document_id: uuid.UUID) -> list[models.Chunk]:
        result = await self.session.execute(
            select(models.Chunk)
            .where(models.Chunk.document_id == document_id)
            .order_by(models.Chunk.chunk_index)
        )
        return list(result.scalars().all())

    async def count_by_document(self, document_id: uuid.UUID) -> int:
        result = await self.session.execute(
            select(func.count())
            .select_from(models.Chunk)
            .where(models.Chunk.document_id == document_id)
        )
        return result.scalar_one()

    async def list_without_embeddings(
        self, *, within_first: int | None = None
    ) -> list[models.Chunk]:
        """Chunks still waiting to be embedded, in corpus order.

        `within_first` narrows the search to the first N chunks of the corpus
        rather than capping how many rows come back. That keeps a repeated run
        idempotent: the same value looks at the same window, so once it is
        embedded there is nothing left to do.
        """
        order = (models.Chunk.document_id, models.Chunk.chunk_index)
        statement = select(models.Chunk).where(models.Chunk.embedding.is_(None))
        if within_first is not None:
            window = select(models.Chunk.id).order_by(*order).limit(within_first)
            statement = statement.where(models.Chunk.id.in_(window))
        result = await self.session.execute(statement.order_by(*order))
        return list(result.scalars().all())

    async def count_without_embeddings(self) -> int:
        result = await self.session.execute(
            select(func.count())
            .select_from(models.Chunk)
            .where(models.Chunk.embedding.is_(None))
        )
        return result.scalar_one()

    async def set_embeddings(
        self, embeddings: Mapping[uuid.UUID, Sequence[float]]
    ) -> int:
        """Attach vectors to existing chunks in one statement.

        Content and chunk_index are untouched -- this only fills the column
        that ingestion left NULL.
        """
        if not embeddings:
            return 0
        await self.session.execute(
            update(models.Chunk),
            [
                {"id": chunk_id, "embedding": list(vector)}
                for chunk_id, vector in embeddings.items()
            ],
        )
        await self.session.flush()
        return len(embeddings)

    async def search_similar(
        self,
        query_embedding: Sequence[float],
        *,
        top_k: int,
        max_distance: float,
    ) -> list[Row]:
        """Nearest chunks by cosine distance, closest first, with provenance.

        pgvector does the search: the ORDER BY on the `<=>` operator with a
        LIMIT is what the HNSW index serves. The distance filter rides along as
        a filter over that ordered scan -- verified with EXPLAIN, the index is
        still used -- and it is safe to apply in SQL because rows arrive in
        distance order, so nothing past the threshold could have matched.
        """
        distance = models.Chunk.embedding.cosine_distance(
            list(query_embedding)
        ).label("distance")
        result = await self.session.execute(
            select(
                models.Chunk.id.label("chunk_id"),
                models.Chunk.document_id,
                models.Chunk.content,
                models.Chunk.chunk_index,
                distance,
                models.Document.title,
                models.Document.guest,
                models.Document.source_url,
                models.Document.source_path,
            )
            .join(models.Document, models.Document.id == models.Chunk.document_id)
            .where(models.Chunk.embedding.isnot(None))
            .where(distance <= max_distance)
            .order_by(distance)
            .limit(top_k)
        )
        return list(result.all())

    async def delete_by_document(self, document_id: uuid.UUID) -> int:
        """Re-chunking replaces chunks wholesale: boundaries shift, so old
        indexes do not survive and updating in place would leave orphans."""
        result = await self.session.execute(
            delete(models.Chunk).where(models.Chunk.document_id == document_id)
        )
        return result.rowcount or 0
