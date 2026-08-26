"""Embedding provider and the embed command.

No real Ollama: the HTTP call is stubbed at the transport boundary for provider
tests, and the provider itself is stubbed for pipeline tests. The database
tests are real -- a vector column is the point.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from pathlib import Path

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.config import Settings
from app.db import models
from app.db.repositories import ChunkRepository, DocumentRepository
from app.embeddings import EmbeddingProvider, OllamaEmbeddingProvider
from app.errors import EmbeddingError
from app.ingestion.embed import embed_pending

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


def a_vector(fill: float = 0.1, dimensions: int = DIMENSIONS) -> list[float]:
    return [fill] * dimensions


# ---------------------------------------------------------------------------
# Provider
# ---------------------------------------------------------------------------


@pytest.fixture
def provider_with(monkeypatch: pytest.MonkeyPatch):
    """Build a provider whose HTTP calls are served by a handler function."""

    def build(handler, **setting_overrides) -> OllamaEmbeddingProvider:
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        monkeypatch.setattr("app.embeddings.get_http_client", lambda: client)
        return OllamaEmbeddingProvider(make_settings(**setting_overrides))

    return build


class TestOllamaProvider:
    async def test_returns_one_vector_per_text(self, provider_with) -> None:
        captured: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            import json

            captured.update(json.loads(request.content))
            count = len(captured["input"])
            return httpx.Response(200, json={"embeddings": [a_vector()] * count})

        provider = provider_with(handler)

        vectors = await provider.embed(["retention", "growth", "activation"])

        assert len(vectors) == 3
        assert captured["model"] == "nomic-embed-text"
        assert captured["input"] == ["retention", "growth", "activation"]

    async def test_vectors_have_the_configured_dimension(self, provider_with) -> None:
        provider = provider_with(
            lambda _r: httpx.Response(200, json={"embeddings": [a_vector()]})
        )

        vectors = await provider.embed(["one"])

        assert len(vectors[0]) == DIMENSIONS == provider.dimensions

    async def test_wrong_dimension_is_rejected(self, provider_with) -> None:
        """A short vector must never reach the database."""
        provider = provider_with(
            lambda _r: httpx.Response(
                200, json={"embeddings": [a_vector(dimensions=384)]}
            )
        )

        with pytest.raises(EmbeddingError, match="384 dimensions"):
            await provider.embed(["one"])

    async def test_wrong_dimension_anywhere_in_the_batch_is_rejected(self, provider_with) -> None:
        provider = provider_with(
            lambda _r: httpx.Response(
                200,
                json={
                    "embeddings": [
                        a_vector(),
                        a_vector(),
                        a_vector(dimensions=767),
                    ]
                },
            )
        )

        with pytest.raises(EmbeddingError, match="position 2"):
            await provider.embed(["a", "b", "c"])

    async def test_missing_vectors_are_rejected(self, provider_with) -> None:
        provider = provider_with(
            lambda _r: httpx.Response(200, json={"embeddings": [a_vector()]})
        )

        with pytest.raises(EmbeddingError, match="1 embeddings for 2 inputs"):
            await provider.embed(["a", "b"])

    async def test_empty_response_is_rejected(self, provider_with) -> None:
        provider = provider_with(lambda _r: httpx.Response(200, json={}))

        with pytest.raises(EmbeddingError):
            await provider.embed(["a"])

    async def test_empty_input_makes_no_request(self, provider_with) -> None:
        def handler(_request: httpx.Request) -> httpx.Response:
            raise AssertionError("should not call Ollama for zero texts")

        provider = provider_with(handler)

        assert await provider.embed([]) == []

    async def test_unreachable_ollama_is_reported_clearly(self, provider_with) -> None:
        def handler(_request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("connection refused")

        provider = provider_with(handler)

        with pytest.raises(EmbeddingError, match="not reachable"):
            await provider.embed(["a"])

    async def test_timeout_is_reported_clearly(self, provider_with) -> None:
        def handler(_request: httpx.Request) -> httpx.Response:
            raise httpx.ReadTimeout("too slow")

        provider = provider_with(handler)

        with pytest.raises(EmbeddingError, match="did not respond within"):
            await provider.embed(["a"])

    async def test_missing_model_suggests_pulling_it(self, provider_with) -> None:
        provider = provider_with(lambda _r: httpx.Response(404, json={"error": "not found"}))

        with pytest.raises(EmbeddingError, match="ollama pull nomic-embed-text"):
            await provider.embed(["a"])

    async def test_malformed_json_is_reported_clearly(self, provider_with) -> None:
        provider = provider_with(
            lambda _r: httpx.Response(200, content=b"<html>not json</html>")
        )

        with pytest.raises(EmbeddingError, match="malformed"):
            await provider.embed(["a"])

    async def test_errors_carry_the_typed_code(self, provider_with) -> None:
        """The existing error contract, not a new one."""
        provider = provider_with(lambda _r: httpx.Response(200, json={}))

        with pytest.raises(EmbeddingError) as caught:
            await provider.embed(["a"])

        assert caught.value.code == "embedding_failed"

    async def test_no_credentials_appear_in_errors(self, provider_with) -> None:
        provider = provider_with(
            lambda _r: httpx.Response(500, json={"error": "boom"}),
            database_url="postgresql://user:supersecret@host/db",
        )

        with pytest.raises(EmbeddingError) as caught:
            await provider.embed(["a"])

        assert "supersecret" not in str(caught.value)


# ---------------------------------------------------------------------------
# The pipeline
# ---------------------------------------------------------------------------


class StubProvider(EmbeddingProvider):
    """Records the batches it was asked to embed."""

    def __init__(self, settings: Settings, *, fail_on_batch: int | None = None) -> None:
        super().__init__(settings)
        self.batches: list[list[str]] = []
        self.fail_on_batch = fail_on_batch

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        self.batches.append(list(texts))
        if self.fail_on_batch is not None and len(self.batches) == self.fail_on_batch:
            raise EmbeddingError("Ollama fell over.")
        return [a_vector(0.1 + index / 1000) for index in range(len(texts))]


@pytest_asyncio.fixture
async def embedding_env(migrated_database: str):
    """A document with chunks that have no embeddings, cleaned up afterwards."""
    engine = create_async_engine(migrated_database, poolclass=NullPool)
    factory = async_sessionmaker(bind=engine, expire_on_commit=False)

    async def clear() -> None:
        async with engine.begin() as conn:
            await conn.execute(text("DELETE FROM documents"))

    await clear()

    async def seed(count: int) -> list[uuid.UUID]:
        async with factory() as session:
            document = await DocumentRepository(session).create(
                source_path="episodes/seed/transcript.md",
                title="Seed",
                content_hash="a" * 64,
            )
            chunks = [
                models.Chunk(
                    document_id=document.id,
                    chunk_index=index,
                    content=f"chunk {index} content",
                    content_hash=f"{index:064d}",
                )
                for index in range(count)
            ]
            await ChunkRepository(session).bulk_insert(chunks)
            await session.commit()
            return [chunk.id for chunk in chunks]

    try:
        yield factory, seed
    finally:
        await clear()
        await engine.dispose()


async def embedded_count(factory) -> int:
    async with factory() as session:
        return (
            await session.execute(
                select(func.count())
                .select_from(models.Chunk)
                .where(models.Chunk.embedding.isnot(None))
            )
        ).scalar_one()


class TestSelection:
    async def test_only_chunks_without_embeddings_are_selected(
        self, embedding_env
    ) -> None:
        factory, seed = embedding_env
        ids = await seed(5)
        async with factory() as session:
            await ChunkRepository(session).set_embeddings(
                {ids[0]: a_vector(), ids[1]: a_vector()}
            )
            await session.commit()

        async with factory() as session:
            pending = await ChunkRepository(session).list_without_embeddings()

        assert {chunk.id for chunk in pending} == set(ids[2:])

    async def test_pending_are_ordered_by_position_in_the_corpus(
        self, embedding_env
    ) -> None:
        factory, seed = embedding_env
        await seed(6)

        async with factory() as session:
            pending = await ChunkRepository(session).list_without_embeddings()

        assert [c.chunk_index for c in pending] == [0, 1, 2, 3, 4, 5]

    async def test_count_without_embeddings(self, embedding_env) -> None:
        factory, seed = embedding_env
        await seed(4)

        async with factory() as session:
            assert await ChunkRepository(session).count_without_embeddings() == 4


class TestPersistence:
    async def test_embeddings_are_written(self, embedding_env) -> None:
        factory, seed = embedding_env
        await seed(3)

        run = await embed_pending(
            make_settings(),
            session_factory=factory,
            provider=StubProvider(make_settings()),
        )

        assert run.embedded == 3
        assert await embedded_count(factory) == 3

    async def test_stored_vectors_have_the_right_width(self, embedding_env) -> None:
        factory, seed = embedding_env
        await seed(2)

        await embed_pending(
            make_settings(),
            session_factory=factory,
            provider=StubProvider(make_settings()),
        )

        async with factory() as session:
            chunks = (
                (await session.execute(select(models.Chunk))).scalars().all()
            )
        assert all(len(chunk.embedding) == DIMENSIONS for chunk in chunks)

    async def test_content_and_indexes_are_untouched(self, embedding_env) -> None:
        factory, seed = embedding_env
        await seed(4)

        await embed_pending(
            make_settings(),
            session_factory=factory,
            provider=StubProvider(make_settings()),
        )

        async with factory() as session:
            chunks = (
                (
                    await session.execute(
                        select(models.Chunk).order_by(models.Chunk.chunk_index)
                    )
                )
                .scalars()
                .all()
            )
        assert [c.chunk_index for c in chunks] == [0, 1, 2, 3]
        assert [c.content for c in chunks] == [f"chunk {i} content" for i in range(4)]

    async def test_documents_are_not_recreated(self, embedding_env) -> None:
        factory, seed = embedding_env
        await seed(2)

        await embed_pending(
            make_settings(),
            session_factory=factory,
            provider=StubProvider(make_settings()),
        )

        async with factory() as session:
            count = (
                await session.execute(select(func.count()).select_from(models.Document))
            ).scalar_one()
        assert count == 1


class TestBatching:
    async def test_batch_size_comes_from_configuration(self, embedding_env) -> None:
        factory, seed = embedding_env
        await seed(10)
        provider = StubProvider(make_settings())

        run = await embed_pending(
            make_settings(embedding_batch_size=4),
            session_factory=factory,
            provider=provider,
        )

        assert [len(batch) for batch in provider.batches] == [4, 4, 2]
        assert run.batches == 3

    async def test_a_single_batch_is_one_request(self, embedding_env) -> None:
        """Never one request per chunk."""
        factory, seed = embedding_env
        await seed(32)
        provider = StubProvider(make_settings())

        await embed_pending(
            make_settings(embedding_batch_size=32),
            session_factory=factory,
            provider=provider,
        )

        assert len(provider.batches) == 1
        assert len(provider.batches[0]) == 32

    async def test_nothing_pending_makes_no_request(self, embedding_env) -> None:
        factory, _seed = embedding_env
        provider = StubProvider(make_settings())

        run = await embed_pending(
            make_settings(), session_factory=factory, provider=provider
        )

        assert run.pending == 0
        assert run.embedded == 0
        assert provider.batches == []


class TestIdempotence:
    async def test_rerunning_does_no_work(self, embedding_env) -> None:
        factory, seed = embedding_env
        await seed(5)
        first = await embed_pending(
            make_settings(),
            session_factory=factory,
            provider=StubProvider(make_settings()),
        )

        provider = StubProvider(make_settings())
        second = await embed_pending(
            make_settings(), session_factory=factory, provider=provider
        )

        assert first.embedded == 5
        assert second.embedded == 0
        assert provider.batches == []

    async def test_existing_embeddings_are_not_regenerated(
        self, embedding_env
    ) -> None:
        """Only the new chunks get embedded when the corpus grows."""
        factory, seed = embedding_env
        await seed(3)
        await embed_pending(
            make_settings(),
            session_factory=factory,
            provider=StubProvider(make_settings()),
        )
        async with factory() as session:
            document = (await session.execute(select(models.Document))).scalar_one()
            await ChunkRepository(session).bulk_insert(
                [
                    models.Chunk(
                        document_id=document.id,
                        chunk_index=index,
                        content=f"new chunk {index}",
                        content_hash=f"{index + 100:064d}",
                    )
                    for index in range(3, 5)
                ]
            )
            await session.commit()

        provider = StubProvider(make_settings())
        run = await embed_pending(
            make_settings(), session_factory=factory, provider=provider
        )

        assert run.embedded == 2
        assert provider.batches == [["new chunk 3", "new chunk 4"]]
        assert await embedded_count(factory) == 5


class TestLimit:
    """`--limit N` scopes the run to the first N chunks in corpus order."""

    async def test_limit_scopes_the_run(self, embedding_env) -> None:
        factory, seed = embedding_env
        await seed(10)

        run = await embed_pending(
            make_settings(embedding_batch_size=4),
            limit=3,
            session_factory=factory,
            provider=StubProvider(make_settings()),
        )

        assert run.pending == 3
        assert run.embedded == 3
        assert await embedded_count(factory) == 3

    async def test_limit_selects_the_first_chunks_in_corpus_order(
        self, embedding_env
    ) -> None:
        factory, seed = embedding_env
        await seed(10)

        await embed_pending(
            make_settings(),
            limit=3,
            session_factory=factory,
            provider=StubProvider(make_settings()),
        )

        async with factory() as session:
            embedded = (
                (
                    await session.execute(
                        select(models.Chunk.chunk_index)
                        .where(models.Chunk.embedding.isnot(None))
                        .order_by(models.Chunk.chunk_index)
                    )
                )
                .scalars()
                .all()
            )
        assert embedded == [0, 1, 2]

    async def test_rerunning_the_same_limit_does_nothing(
        self, embedding_env
    ) -> None:
        """The property that makes the flag safe: idempotent at every limit."""
        factory, seed = embedding_env
        await seed(10)
        await embed_pending(
            make_settings(),
            limit=3,
            session_factory=factory,
            provider=StubProvider(make_settings()),
        )

        provider = StubProvider(make_settings())
        run = await embed_pending(
            make_settings(), limit=3, session_factory=factory, provider=provider
        )

        assert run.pending == 0
        assert run.embedded == 0
        assert provider.batches == []
        assert await embedded_count(factory) == 3

    async def test_a_wider_limit_embeds_only_the_gap(self, embedding_env) -> None:
        factory, seed = embedding_env
        await seed(10)
        await embed_pending(
            make_settings(),
            limit=3,
            session_factory=factory,
            provider=StubProvider(make_settings()),
        )

        run = await embed_pending(
            make_settings(),
            limit=10,
            session_factory=factory,
            provider=StubProvider(make_settings()),
        )

        assert run.embedded == 7, "the 3 already embedded are not redone"
        assert await embedded_count(factory) == 10

    async def test_limit_larger_than_the_corpus_is_fine(
        self, embedding_env
    ) -> None:
        factory, seed = embedding_env
        await seed(2)

        run = await embed_pending(
            make_settings(),
            limit=100,
            session_factory=factory,
            provider=StubProvider(make_settings()),
        )

        assert run.embedded == 2


class TestFailureSafety:
    async def test_a_database_failure_is_not_mistaken_for_success(
        self, embedding_env
    ) -> None:
        """Observed for real: a DNS blip mid-run must fail loudly, not silently."""
        from sqlalchemy.exc import OperationalError

        factory, seed = embedding_env
        await seed(4)

        class BrokenFactory:
            def __call__(self):
                raise OperationalError("connect", None, Exception("no route to host"))

        with pytest.raises(OperationalError):
            await embed_pending(
                make_settings(),
                session_factory=BrokenFactory(),
                provider=StubProvider(make_settings()),
            )

    async def test_a_failed_batch_leaves_its_chunks_null(
        self, embedding_env
    ) -> None:
        factory, seed = embedding_env
        await seed(10)

        with pytest.raises(EmbeddingError):
            await embed_pending(
                make_settings(embedding_batch_size=4),
                session_factory=factory,
                provider=StubProvider(make_settings(), fail_on_batch=2),
            )

        # First batch committed, the failing batch and everything after is NULL.
        assert await embedded_count(factory) == 4

    async def test_the_failure_is_not_swallowed(self, embedding_env) -> None:
        """Reporting success after a failed batch would be the worst outcome."""
        factory, seed = embedding_env
        await seed(4)

        with pytest.raises(EmbeddingError, match="fell over"):
            await embed_pending(
                make_settings(embedding_batch_size=2),
                session_factory=factory,
                provider=StubProvider(make_settings(), fail_on_batch=1),
            )

        assert await embedded_count(factory) == 0

    async def test_a_rerun_after_failure_completes_the_work(
        self, embedding_env
    ) -> None:
        factory, seed = embedding_env
        await seed(10)
        with pytest.raises(EmbeddingError):
            await embed_pending(
                make_settings(embedding_batch_size=4),
                session_factory=factory,
                provider=StubProvider(make_settings(), fail_on_batch=2),
            )

        run = await embed_pending(
            make_settings(embedding_batch_size=4),
            session_factory=factory,
            provider=StubProvider(make_settings()),
        )

        assert run.embedded == 6
        assert await embedded_count(factory) == 10

    async def test_a_bad_dimension_writes_nothing(self, embedding_env) -> None:
        """The validation boundary, exercised through the pipeline."""
        factory, seed = embedding_env
        await seed(3)

        class ShortVectorProvider(EmbeddingProvider):
            async def embed(self, texts: Sequence[str]) -> list[list[float]]:
                raise EmbeddingError("returned 384 dimensions; expected 768")

        with pytest.raises(EmbeddingError, match="384 dimensions"):
            await embed_pending(
                make_settings(),
                session_factory=factory,
                provider=ShortVectorProvider(make_settings()),
            )

        assert await embedded_count(factory) == 0
