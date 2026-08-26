"""Vector retrieval.

Embeddings here are hand-built unit vectors, so cosine distances are exact and
assertions are about behaviour rather than about what a model happens to think.
No real Ollama: the embedding provider is stubbed. The search itself runs
against real PostgreSQL, because pgvector doing the work is the point.
"""

from __future__ import annotations

from collections.abc import Sequence

import pytest
import pytest_asyncio
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.config import Settings
from app.db import models
from app.db.repositories import ChunkRepository, DocumentRepository
from app.embeddings import EmbeddingProvider
from app.errors import EmbeddingError
from app.retrieval import retrieve

DIMENSIONS = 768


def make_settings(**overrides: object) -> Settings:
    import os

    base: dict[str, object] = {
        "_env_file": None,
        "database_url": os.environ["DATABASE_URL"],
        "app_env": "test",
        "log_level": "WARNING",
    }
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


def vector(*components: float) -> list[float]:
    """A 768-wide vector with `components` at the front and zeros after."""
    return list(components) + [0.0] * (DIMENSIONS - len(components))


# Cosine distance from vector(1, 0) is 1 - cos(theta):
#   vector(1, 0)      -> 0.0
#   vector(0.8, 0.6)  -> 0.2
#   vector(0.6, 0.8)  -> 0.4
#   vector(0, 1)      -> 1.0
QUERY = vector(1.0, 0.0)
NEAR = vector(1.0, 0.0)
MID = vector(0.8, 0.6)
FAR = vector(0.6, 0.8)
UNRELATED = vector(0.0, 1.0)


class StubProvider(EmbeddingProvider):
    """Returns a fixed vector, and records what it was asked to embed."""

    def __init__(self, settings: Settings, embedding: list[float] | None = None) -> None:
        super().__init__(settings)
        self.embedding = embedding if embedding is not None else QUERY
        self.calls: list[list[str]] = []

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        self.calls.append(list(texts))
        return [self.embedding for _ in texts]


class FailingProvider(EmbeddingProvider):
    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        raise EmbeddingError("Ollama is not reachable.")


@pytest_asyncio.fixture
async def corpus(migrated_database: str):
    """Two episodes with chunks at known distances from QUERY."""
    engine = create_async_engine(migrated_database, poolclass=NullPool)
    factory = async_sessionmaker(bind=engine, expire_on_commit=False)

    async def clear() -> None:
        async with engine.begin() as conn:
            await conn.execute(text("DELETE FROM documents"))

    await clear()

    async def seed(chunks: list[tuple[str, list[float] | None]]) -> None:
        """chunks: (content, embedding). A None embedding stays unembedded."""
        async with factory() as session:
            document = await DocumentRepository(session).create(
                source_path="episodes/casey-winters/transcript.md",
                title="Why product managers are unprepared",
                content_hash="a" * 64,
                source_url="https://www.youtube.com/watch?v=abc",
                guest="Casey Winters",
            )
            await ChunkRepository(session).bulk_insert(
                [
                    models.Chunk(
                        document_id=document.id,
                        chunk_index=index,
                        content=content,
                        content_hash=f"{index:064d}",
                        embedding=embedding,
                    )
                    for index, (content, embedding) in enumerate(chunks)
                ]
            )
            await session.commit()

    try:
        yield factory, seed
    finally:
        await clear()
        await engine.dispose()


class TestQueryEmbedding:
    async def test_the_query_is_embedded(self, corpus) -> None:
        factory, seed = corpus
        await seed([("retention", NEAR), ("growth", MID)])
        provider = StubProvider(make_settings())

        async with factory() as session:
            await retrieve(
                session, "how do I retain users?", settings=make_settings(), provider=provider
            )

        assert provider.calls == [["how do I retain users?"]]

    async def test_only_the_query_is_embedded_not_the_corpus(self, corpus) -> None:
        """A question must not re-embed documents."""
        factory, seed = corpus
        await seed([("a", NEAR), ("b", MID), ("c", FAR)])
        provider = StubProvider(make_settings())

        async with factory() as session:
            await retrieve(session, "a question", settings=make_settings(), provider=provider)

        assert len(provider.calls) == 1
        assert len(provider.calls[0]) == 1

    async def test_the_query_vector_has_the_configured_width(self, corpus) -> None:
        factory, seed = corpus
        await seed([("a", NEAR), ("b", MID)])
        provider = StubProvider(make_settings())

        async with factory() as session:
            result = await retrieve(
                session, "q", settings=make_settings(), provider=provider
            )

        assert len(provider.embedding) == DIMENSIONS == provider.dimensions
        assert result.chunks

    async def test_a_blank_query_does_not_call_the_provider(self, corpus) -> None:
        factory, seed = corpus
        await seed([("a", NEAR)])
        provider = StubProvider(make_settings())

        async with factory() as session:
            result = await retrieve(
                session, "   ", settings=make_settings(), provider=provider
            )

        assert provider.calls == []
        assert result.chunks == []
        assert result.sufficient is False


class TestSearch:
    async def test_returns_the_nearest_chunks(self, corpus) -> None:
        factory, seed = corpus
        await seed([("near", NEAR), ("unrelated", UNRELATED), ("mid", MID)])

        async with factory() as session:
            result = await retrieve(
                session,
                "q",
                settings=make_settings(),
                provider=StubProvider(make_settings()),
            )

        assert [c.content for c in result.chunks] == ["near", "mid"]

    async def test_results_are_ordered_by_distance(self, corpus) -> None:
        factory, seed = corpus
        await seed([("far", FAR), ("near", NEAR), ("mid", MID)])

        async with factory() as session:
            result = await retrieve(
                session,
                "q",
                settings=make_settings(),
                provider=StubProvider(make_settings()),
            )

        distances = [c.distance for c in result.chunks]
        assert distances == sorted(distances)
        assert [c.content for c in result.chunks] == ["near", "mid", "far"]

    async def test_distances_are_cosine_distances(self, corpus) -> None:
        """0.0 / 0.2 / 0.4 for the three known angles."""
        factory, seed = corpus
        await seed([("near", NEAR), ("mid", MID), ("far", FAR)])

        async with factory() as session:
            result = await retrieve(
                session,
                "q",
                settings=make_settings(),
                provider=StubProvider(make_settings()),
            )

        assert [round(c.distance, 4) for c in result.chunks] == [0.0, 0.2, 0.4]

    async def test_top_k_is_respected(self, corpus) -> None:
        factory, seed = corpus
        await seed([(f"chunk {i}", NEAR) for i in range(10)])

        async with factory() as session:
            result = await retrieve(
                session,
                "q",
                settings=make_settings(retrieval_top_k=3),
                provider=StubProvider(make_settings()),
            )

        assert len(result.chunks) == 3

    async def test_unembedded_chunks_are_ignored(self, corpus) -> None:
        factory, seed = corpus
        await seed([("embedded", NEAR), ("not yet embedded", None)])

        async with factory() as session:
            result = await retrieve(
                session,
                "q",
                settings=make_settings(),
                provider=StubProvider(make_settings()),
            )

        assert [c.content for c in result.chunks] == ["embedded"]

    async def test_an_empty_corpus_returns_nothing(self, corpus) -> None:
        factory, _seed = corpus

        async with factory() as session:
            result = await retrieve(
                session,
                "q",
                settings=make_settings(),
                provider=StubProvider(make_settings()),
            )

        assert result.chunks == []
        assert result.sufficient is False

    async def test_the_search_runs_in_postgresql(self, corpus) -> None:
        """pgvector does the work: the HNSW index serves the ordering.

        Sequential scan is disabled so the assertion is about the index being
        usable for this operator, not about what the planner picks for three
        rows of test data.
        """
        factory, seed = corpus
        await seed([("near", NEAR), ("mid", MID)])
        literal = "[" + ",".join(str(v) for v in QUERY) + "]"

        async with factory() as session:
            await session.execute(text("SET LOCAL enable_seqscan = off"))
            plan = "\n".join(
                row[0]
                for row in await session.execute(
                    text(
                        "EXPLAIN SELECT id FROM chunks "
                        f"ORDER BY embedding <=> '{literal}'::vector LIMIT 8"
                    )
                )
            )

        assert "ix_chunks_embedding_hnsw" in plan
        assert "<=>" in plan


class TestRelevanceThreshold:
    async def test_chunks_beyond_the_threshold_are_dropped(self, corpus) -> None:
        factory, seed = corpus
        await seed([("near", NEAR), ("mid", MID), ("unrelated", UNRELATED)])

        async with factory() as session:
            result = await retrieve(
                session,
                "q",
                settings=make_settings(retrieval_max_distance=0.3),
                provider=StubProvider(make_settings()),
            )

        assert [c.content for c in result.chunks] == ["near", "mid"]
        assert all(c.distance <= 0.3 for c in result.chunks)

    async def test_a_tighter_threshold_keeps_less(self, corpus) -> None:
        factory, seed = corpus
        await seed([("near", NEAR), ("mid", MID), ("far", FAR)])

        async with factory() as session:
            result = await retrieve(
                session,
                "q",
                settings=make_settings(retrieval_max_distance=0.1),
                provider=StubProvider(make_settings()),
            )

        assert [c.content for c in result.chunks] == ["near"]


class TestInsufficientEvidence:
    async def test_an_unrelated_query_yields_no_evidence(self, corpus) -> None:
        """The nearest vector is not automatically relevant."""
        factory, seed = corpus
        await seed([("about something else", UNRELATED)])

        async with factory() as session:
            result = await retrieve(
                session,
                "q",
                settings=make_settings(),
                provider=StubProvider(make_settings()),
            )

        assert result.chunks == []
        assert result.sufficient is False

    async def test_fewer_than_the_minimum_is_insufficient(self, corpus) -> None:
        factory, seed = corpus
        await seed([("only one relevant", NEAR), ("unrelated", UNRELATED)])

        async with factory() as session:
            result = await retrieve(
                session,
                "q",
                settings=make_settings(retrieval_min_chunks=2),
                provider=StubProvider(make_settings()),
            )

        assert len(result.chunks) == 1
        assert result.sufficient is False, "one chunk is below the minimum"

    async def test_meeting_the_minimum_is_sufficient(self, corpus) -> None:
        factory, seed = corpus
        await seed([("one", NEAR), ("two", MID)])

        async with factory() as session:
            result = await retrieve(
                session,
                "q",
                settings=make_settings(retrieval_min_chunks=2),
                provider=StubProvider(make_settings()),
            )

        assert len(result.chunks) == 2
        assert result.sufficient is True

    async def test_insufficient_results_still_carry_what_was_found(
        self, corpus
    ) -> None:
        """The caller may want to log the near-miss; it just must not answer."""
        factory, seed = corpus
        await seed([("weak match", MID)])

        async with factory() as session:
            result = await retrieve(
                session,
                "q",
                settings=make_settings(retrieval_min_chunks=3),
                provider=StubProvider(make_settings()),
            )

        assert result.sufficient is False
        assert len(result.chunks) == 1


class TestProvenance:
    async def test_every_result_can_be_attributed(self, corpus) -> None:
        factory, seed = corpus
        await seed([("a passage", NEAR), ("another", MID)])

        async with factory() as session:
            result = await retrieve(
                session,
                "q",
                settings=make_settings(),
                provider=StubProvider(make_settings()),
            )

        chunk = result.chunks[0]
        assert chunk.title == "Why product managers are unprepared"
        assert chunk.guest == "Casey Winters"
        assert chunk.source_url == "https://www.youtube.com/watch?v=abc"
        assert chunk.source_path == "episodes/casey-winters/transcript.md"
        assert chunk.chunk_index == 0
        assert chunk.chunk_id is not None
        assert chunk.document_id is not None

    async def test_the_query_is_echoed_back(self, corpus) -> None:
        factory, seed = corpus
        await seed([("a", NEAR), ("b", MID)])

        async with factory() as session:
            result = await retrieve(
                session,
                "  how do I grow?  ",
                settings=make_settings(),
                provider=StubProvider(make_settings()),
            )

        assert result.query == "how do I grow?"


class TestSideEffects:
    async def test_retrieval_does_not_modify_the_corpus(self, corpus) -> None:
        factory, seed = corpus
        await seed([("one", NEAR), ("two", MID), ("three", FAR)])

        async with factory() as session:
            before = (
                (
                    await session.execute(
                        select(
                            models.Chunk.content,
                            models.Chunk.chunk_index,
                            models.Chunk.content_hash,
                            models.Chunk.embedding,
                        ).order_by(models.Chunk.chunk_index)
                    )
                )
                .all()
            )

        async with factory() as session:
            await retrieve(
                session,
                "q",
                settings=make_settings(),
                provider=StubProvider(make_settings()),
            )

        async with factory() as session:
            after = (
                (
                    await session.execute(
                        select(
                            models.Chunk.content,
                            models.Chunk.chunk_index,
                            models.Chunk.content_hash,
                            models.Chunk.embedding,
                        ).order_by(models.Chunk.chunk_index)
                    )
                )
                .all()
            )

        assert [(r.content, r.chunk_index, r.content_hash) for r in before] == [
            (r.content, r.chunk_index, r.content_hash) for r in after
        ]
        assert all(
            list(b.embedding) == list(a.embedding) for b, a in zip(before, after)
        )


class TestFailures:
    async def test_an_embedding_failure_propagates(self, corpus) -> None:
        """Retrieval must not swallow a provider failure and return nothing."""
        factory, seed = corpus
        await seed([("a", NEAR)])

        async with factory() as session:
            with pytest.raises(EmbeddingError, match="not reachable"):
                await retrieve(
                    session,
                    "q",
                    settings=make_settings(),
                    provider=FailingProvider(make_settings()),
                )
