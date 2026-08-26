"""Persistence behaviour, against a real PostgreSQL with pgvector.

These exercise the repositories rather than raw SQL, because the repositories
are what the application will call. Where the point of a test is a *database*
guarantee -- a cascade, a check constraint, a vector width -- it is asserted
against the database, not against the ORM's opinion of it.
"""

from __future__ import annotations

import uuid
from datetime import date

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError, StatementError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.constants import (
    ARTIFACT_HTML,
    ARTIFACT_MARKDOWN,
    ROLE_ASSISTANT,
    ROLE_SYSTEM,
    ROLE_USER,
)
from app.db import models
from app.db.repositories import (
    ArtifactRepository,
    ChunkRepository,
    DocumentRepository,
    MessageRepository,
    SessionRepository,
    UserRepository,
)

EMBEDDING_DIMENSIONS = models.EMBEDDING_DIMENSIONS


def a_hash(seed: str) -> str:
    """A 64-character value shaped like a sha256 digest."""
    return seed.encode().hex().ljust(64, "0")[:64]


def an_embedding(fill: float = 0.1) -> list[float]:
    """A vector of the configured width."""
    return [fill] * EMBEDDING_DIMENSIONS


async def a_user(session: AsyncSession) -> models.User:
    return await UserRepository(session).create()


async def a_session(session: AsyncSession) -> models.Session:
    user = await a_user(session)
    return await SessionRepository(session).create(user.id)


async def a_document(
    session: AsyncSession, *, path: str = "transcripts/ep-001.md"
) -> models.Document:
    return await DocumentRepository(session).create(
        source_path=path,
        title="How to build a growth loop",
        content_hash=a_hash("ep1"),
        source_url="https://www.lennyspodcast.com/ep-001",
        guest="Casey Winters",
        publish_date=date(2024, 3, 1),
    )


# ---------------------------------------------------------------------------
# Users and sessions
# ---------------------------------------------------------------------------


class TestUsers:
    async def test_create_assigns_id_and_timestamps(
        self, db_session: AsyncSession
    ) -> None:
        user = await UserRepository(db_session).create()

        assert isinstance(user.id, uuid.UUID)
        assert user.created_at is not None
        assert user.created_at.tzinfo is not None, "timestamps must be tz-aware"
        assert user.user_metadata == {}

    async def test_metadata_round_trips_as_jsonb(
        self, db_session: AsyncSession
    ) -> None:
        repository = UserRepository(db_session)
        user = await repository.create(metadata={"locale": "en-GB", "visits": 3})
        db_session.expunge_all()

        reloaded = await repository.get(user.id)

        assert reloaded is not None
        assert reloaded.user_metadata == {"locale": "en-GB", "visits": 3}

    async def test_get_unknown_id_returns_none(
        self, db_session: AsyncSession
    ) -> None:
        assert await UserRepository(db_session).get(uuid.uuid4()) is None

    async def test_get_or_create_accepts_a_client_minted_id(
        self, db_session: AsyncSession
    ) -> None:
        """A returning visitor sends an id that may predate a database reset."""
        repository = UserRepository(db_session)
        client_id = uuid.uuid4()

        created = await repository.get_or_create(client_id)
        again = await repository.get_or_create(client_id)

        assert created.id == client_id
        assert again.id == client_id


class TestSessions:
    async def test_create_links_to_its_user(self, db_session: AsyncSession) -> None:
        user = await a_user(db_session)

        conversation = await SessionRepository(db_session).create(user.id)

        assert conversation.user_id == user.id

    async def test_user_to_sessions_relationship_loads(
        self, db_session: AsyncSession
    ) -> None:
        user = await a_user(db_session)
        repository = SessionRepository(db_session)
        await repository.create(user.id)
        await repository.create(user.id)
        # Clear the identity map, or `get` returns the instance already in it
        # and ignores the eager-load option -- which then lazy-loads and, in
        # async, raises MissingGreenlet.
        db_session.expunge_all()

        loaded = await db_session.get(
            models.User, user.id, options=[selectinload(models.User.sessions)]
        )

        assert loaded is not None
        assert len(loaded.sessions) == 2
        assert {s.user_id for s in loaded.sessions} == {user.id}

    async def test_list_by_user_is_most_recently_active_first(
        self, db_session: AsyncSession
    ) -> None:
        user = await a_user(db_session)
        repository = SessionRepository(db_session)
        first = await repository.create(user.id)
        second = await repository.create(user.id)

        await repository.touch(first.id)
        listed = await repository.list_by_user(user.id)

        assert [s.id for s in listed] == [first.id, second.id]

    async def test_list_by_user_excludes_other_users(
        self, db_session: AsyncSession
    ) -> None:
        """Session isolation is a product requirement, not a nicety."""
        repository = SessionRepository(db_session)
        mine = await a_user(db_session)
        theirs = await a_user(db_session)
        await repository.create(mine.id)
        await repository.create(theirs.id)

        assert len(await repository.list_by_user(mine.id)) == 1

    async def test_touch_moves_updated_at_forward(
        self, db_session: AsyncSession
    ) -> None:
        conversation = await a_session(db_session)
        repository = SessionRepository(db_session)
        before = conversation.updated_at

        await repository.touch(conversation.id)
        await db_session.refresh(conversation)

        assert conversation.updated_at > before


# ---------------------------------------------------------------------------
# Messages
# ---------------------------------------------------------------------------


class TestMessages:
    async def test_create_persists_role_and_content(
        self, db_session: AsyncSession
    ) -> None:
        conversation = await a_session(db_session)

        message = await MessageRepository(db_session).create(
            session_id=conversation.id,
            role=ROLE_USER,
            content="How do I improve retention?",
        )

        assert message.role == ROLE_USER
        assert message.content == "How do I improve retention?"
        assert message.created_at.tzinfo is not None

    async def test_ordering_is_stable_within_one_transaction(
        self, db_session: AsyncSession
    ) -> None:
        """The case that `now()` would have broken.

        A user turn and the assistant reply are written in a single request. If
        created_at used now() -- transaction start time -- both rows would
        share a timestamp and the conversation could come back reversed.
        """
        conversation = await a_session(db_session)
        repository = MessageRepository(db_session)

        for index in range(6):
            role = ROLE_USER if index % 2 == 0 else ROLE_ASSISTANT
            await repository.create(
                session_id=conversation.id, role=role, content=f"turn {index}"
            )

        listed = await repository.list_by_session(conversation.id)

        assert [m.content for m in listed] == [f"turn {i}" for i in range(6)]
        timestamps = [m.created_at for m in listed]
        assert timestamps == sorted(timestamps)
        assert len(set(timestamps)) == len(timestamps), "timestamps must be distinct"

    async def test_list_by_session_is_scoped(
        self, db_session: AsyncSession
    ) -> None:
        repository = MessageRepository(db_session)
        mine = await a_session(db_session)
        theirs = await a_session(db_session)
        await repository.create(session_id=mine.id, role=ROLE_USER, content="mine")
        await repository.create(session_id=theirs.id, role=ROLE_USER, content="theirs")

        listed = await repository.list_by_session(mine.id)

        assert [m.content for m in listed] == ["mine"]

    async def test_every_supported_role_is_accepted(
        self, db_session: AsyncSession
    ) -> None:
        conversation = await a_session(db_session)
        repository = MessageRepository(db_session)

        for role in (ROLE_USER, ROLE_ASSISTANT, ROLE_SYSTEM):
            message = await repository.create(
                session_id=conversation.id, role=role, content="x"
            )
            assert message.role == role

    async def test_metadata_round_trips_as_jsonb(
        self, db_session: AsyncSession
    ) -> None:
        conversation = await a_session(db_session)
        repository = MessageRepository(db_session)
        provenance = {
            "sources": [{"number": 1, "title": "An episode", "chunk_index": 4}],
            "grounded": True,
            "provider": "ollama",
        }

        message = await repository.create(
            session_id=conversation.id,
            role=ROLE_ASSISTANT,
            content="an answer",
            metadata=provenance,
        )
        db_session.expunge_all()
        reloaded = (await repository.list_by_session(conversation.id))[0]

        assert reloaded.message_metadata == provenance

    async def test_metadata_is_optional(self, db_session: AsyncSession) -> None:
        """User turns and pre-existing rows have none."""
        conversation = await a_session(db_session)

        message = await MessageRepository(db_session).create(
            session_id=conversation.id, role=ROLE_USER, content="a question"
        )

        assert message.message_metadata is None

    async def test_absent_metadata_is_sql_null_not_json_null(
        self, db_session: AsyncSession
    ) -> None:
        """One representation of "no provenance", not two.

        SQLAlchemy stores Python None in a JSON column as JSON 'null' unless
        told otherwise, which would leave `WHERE metadata IS NULL` blind to it
        and break jsonb_typeof/jsonb_object_keys queries.
        """
        conversation = await a_session(db_session)
        await MessageRepository(db_session).create(
            session_id=conversation.id, role=ROLE_USER, content="a question"
        )

        kinds = (
            await db_session.execute(
                text("SELECT jsonb_typeof(metadata) FROM messages")
            )
        ).scalars().all()

        assert kinds == [None], f"expected SQL NULL, got {kinds}"

    async def test_unsupported_role_is_rejected_by_the_database(
        self, db_session: AsyncSession
    ) -> None:
        """The CHECK constraint, not application code, is the guarantee."""
        conversation = await a_session(db_session)

        with pytest.raises(IntegrityError):
            await db_session.execute(
                text(
                    "INSERT INTO messages (id, session_id, role, content) "
                    "VALUES (:id, :session_id, 'moderator', 'x')"
                ),
                {"id": uuid.uuid4(), "session_id": conversation.id},
            )


# ---------------------------------------------------------------------------
# Artifacts
# ---------------------------------------------------------------------------


class TestArtifacts:
    async def test_create_and_get(self, db_session: AsyncSession) -> None:
        conversation = await a_session(db_session)
        repository = ArtifactRepository(db_session)

        created = await repository.create(
            session_id=conversation.id,
            artifact_type=ARTIFACT_MARKDOWN,
            title="Retention playbook",
            content="# Retention\n\nStart with the cohort curve.",
        )
        db_session.expunge_all()
        fetched = await repository.get(created.id)

        assert fetched is not None
        assert fetched.type == ARTIFACT_MARKDOWN
        assert fetched.title == "Retention playbook"
        assert fetched.content.startswith("# Retention")

    async def test_content_is_stored_verbatim(
        self, db_session: AsyncSession
    ) -> None:
        """Sanitisation is a rendering concern; the row keeps the raw output."""
        conversation = await a_session(db_session)
        raw = '<div onclick="alert(1)">hello</div><script>x()</script>'

        artifact = await ArtifactRepository(db_session).create(
            session_id=conversation.id,
            artifact_type=ARTIFACT_HTML,
            title="Landing page",
            content=raw,
        )
        db_session.expunge_all()
        fetched = await ArtifactRepository(db_session).get(artifact.id)

        assert fetched is not None
        assert fetched.content == raw

    async def test_list_by_session_is_newest_first(
        self, db_session: AsyncSession
    ) -> None:
        conversation = await a_session(db_session)
        repository = ArtifactRepository(db_session)
        for index in range(3):
            await repository.create(
                session_id=conversation.id,
                artifact_type=ARTIFACT_MARKDOWN,
                title=f"doc {index}",
                content="x",
            )

        listed = await repository.list_by_session(conversation.id)

        assert len(listed) == 3
        assert listed[0].created_at >= listed[-1].created_at

    async def test_can_be_attributed_to_a_message(
        self, db_session: AsyncSession
    ) -> None:
        conversation = await a_session(db_session)
        message = await MessageRepository(db_session).create(
            session_id=conversation.id, role=ROLE_ASSISTANT, content="here it is"
        )

        artifact = await ArtifactRepository(db_session).create(
            session_id=conversation.id,
            message_id=message.id,
            artifact_type=ARTIFACT_MARKDOWN,
            title="Essay",
            content="# Essay",
        )

        assert artifact.message_id == message.id

    async def test_unsupported_type_is_rejected_by_the_database(
        self, db_session: AsyncSession
    ) -> None:
        conversation = await a_session(db_session)

        with pytest.raises(IntegrityError):
            await db_session.execute(
                text(
                    "INSERT INTO artifacts (id, session_id, type, title, content) "
                    "VALUES (:id, :session_id, 'pdf', 't', 'c')"
                ),
                {"id": uuid.uuid4(), "session_id": conversation.id},
            )


# ---------------------------------------------------------------------------
# Documents
# ---------------------------------------------------------------------------


class TestDocuments:
    async def test_create_persists_provenance(
        self, db_session: AsyncSession
    ) -> None:
        """Everything the UI needs to attribute an answer."""
        document = await a_document(db_session)

        assert document.title == "How to build a growth loop"
        assert document.guest == "Casey Winters"
        assert document.source_url == "https://www.lennyspodcast.com/ep-001"
        assert document.publish_date == date(2024, 3, 1)
        assert document.last_ingested_at is None, "not ingested until it is"

    async def test_source_path_is_unique(self, db_session: AsyncSession) -> None:
        """A transcript path is a document's identity across re-ingests."""
        await a_document(db_session, path="transcripts/ep-001.md")

        with pytest.raises(IntegrityError):
            await a_document(db_session, path="transcripts/ep-001.md")

    async def test_lookup_by_source_path(self, db_session: AsyncSession) -> None:
        repository = DocumentRepository(db_session)
        await a_document(db_session, path="transcripts/ep-042.md")

        found = await repository.get_by_source_path("transcripts/ep-042.md")
        missing = await repository.get_by_source_path("transcripts/nope.md")

        assert found is not None
        assert missing is None

    async def test_lookup_by_content_hash(self, db_session: AsyncSession) -> None:
        repository = DocumentRepository(db_session)
        await a_document(db_session, path="transcripts/ep-001.md")

        found = await repository.list_by_content_hash(a_hash("ep1"))

        assert len(found) == 1
        assert found[0].source_path == "transcripts/ep-001.md"

    async def test_identical_content_under_two_paths_is_allowed(
        self, db_session: AsyncSession
    ) -> None:
        """content_hash is indexed, not unique -- a duplicate must not fail."""
        repository = DocumentRepository(db_session)
        for path in ("transcripts/a.md", "transcripts/b.md"):
            await repository.create(
                source_path=path, title="Same", content_hash=a_hash("same")
            )

        assert len(await repository.list_by_content_hash(a_hash("same"))) == 2

    async def test_upsert_reports_a_new_document_as_changed(
        self, db_session: AsyncSession
    ) -> None:
        document, changed = await DocumentRepository(db_session).upsert(
            source_path="transcripts/new.md", title="New", content_hash=a_hash("v1")
        )

        assert changed is True
        assert document.id is not None

    async def test_upsert_reports_an_unchanged_document_as_unchanged(
        self, db_session: AsyncSession
    ) -> None:
        """This is the signal that makes refresh incremental."""
        repository = DocumentRepository(db_session)
        await repository.upsert(
            source_path="transcripts/x.md", title="X", content_hash=a_hash("v1")
        )

        document, changed = await repository.upsert(
            source_path="transcripts/x.md", title="X", content_hash=a_hash("v1")
        )

        assert changed is False

    async def test_upsert_reports_modified_content_as_changed(
        self, db_session: AsyncSession
    ) -> None:
        repository = DocumentRepository(db_session)
        first, _ = await repository.upsert(
            source_path="transcripts/x.md", title="X", content_hash=a_hash("v1")
        )

        second, changed = await repository.upsert(
            source_path="transcripts/x.md",
            title="X, revised",
            content_hash=a_hash("v2"),
        )

        assert changed is True
        assert second.id == first.id, "identity survives a content change"
        assert second.title == "X, revised"

    async def test_mark_ingested_stamps_the_document(
        self, db_session: AsyncSession
    ) -> None:
        repository = DocumentRepository(db_session)
        document = await a_document(db_session)

        await repository.mark_ingested(document.id)

        assert document.last_ingested_at is not None


# ---------------------------------------------------------------------------
# Chunks
# ---------------------------------------------------------------------------


class TestChunks:
    async def test_bulk_insert_and_read_back_in_order(
        self, db_session: AsyncSession
    ) -> None:
        document = await a_document(db_session)
        repository = ChunkRepository(db_session)

        written = await repository.bulk_insert(
            [
                models.Chunk(
                    document_id=document.id,
                    chunk_index=index,
                    content=f"chunk {index}",
                    content_hash=a_hash(f"c{index}"),
                    embedding=an_embedding(index / 10),
                )
                for index in range(5)
            ]
        )
        listed = await repository.list_by_document(document.id)

        assert written == 5
        assert [c.chunk_index for c in listed] == [0, 1, 2, 3, 4]
        assert [c.content for c in listed] == [f"chunk {i}" for i in range(5)]

    async def test_bulk_insert_of_nothing_is_a_no_op(
        self, db_session: AsyncSession
    ) -> None:
        assert await ChunkRepository(db_session).bulk_insert([]) == 0

    async def test_document_to_chunks_relationship_loads_in_order(
        self, db_session: AsyncSession
    ) -> None:
        document = await a_document(db_session)
        await ChunkRepository(db_session).bulk_insert(
            [
                models.Chunk(
                    document_id=document.id,
                    chunk_index=index,
                    content=f"c{index}",
                    content_hash=a_hash(f"h{index}"),
                    embedding=an_embedding(),
                )
                # Inserted out of order on purpose.
                for index in (2, 0, 1)
            ]
        )
        db_session.expunge_all()

        loaded = await db_session.get(
            models.Document,
            document.id,
            options=[selectinload(models.Document.chunks)],
        )

        assert loaded is not None
        assert [c.chunk_index for c in loaded.chunks] == [0, 1, 2]

    async def test_chunk_can_name_its_source(
        self, db_session: AsyncSession
    ) -> None:
        """Provenance: a retrieved chunk must be attributable to an episode."""
        document = await a_document(db_session)
        await ChunkRepository(db_session).bulk_insert(
            [
                models.Chunk(
                    document_id=document.id,
                    chunk_index=0,
                    content="Retention starts with the cohort curve.",
                    content_hash=a_hash("c0"),
                    embedding=an_embedding(),
                )
            ]
        )

        row = (
            await db_session.execute(
                select(
                    models.Chunk.content,
                    models.Chunk.chunk_index,
                    models.Document.title,
                    models.Document.guest,
                    models.Document.source_url,
                ).join(models.Document, models.Chunk.document_id == models.Document.id)
            )
        ).one()

        assert row.title == "How to build a growth loop"
        assert row.guest == "Casey Winters"
        assert row.source_url == "https://www.lennyspodcast.com/ep-001"
        assert row.chunk_index == 0

    async def test_position_within_a_document_is_unique(
        self, db_session: AsyncSession
    ) -> None:
        document = await a_document(db_session)
        repository = ChunkRepository(db_session)
        await repository.bulk_insert(
            [
                models.Chunk(
                    document_id=document.id,
                    chunk_index=0,
                    content="first",
                    content_hash=a_hash("a"),
                )
            ]
        )

        with pytest.raises(IntegrityError):
            await repository.bulk_insert(
                [
                    models.Chunk(
                        document_id=document.id,
                        chunk_index=0,
                        content="second",
                        content_hash=a_hash("b"),
                    )
                ]
            )

    async def test_negative_position_is_rejected(
        self, db_session: AsyncSession
    ) -> None:
        document = await a_document(db_session)

        with pytest.raises(IntegrityError):
            await ChunkRepository(db_session).bulk_insert(
                [
                    models.Chunk(
                        document_id=document.id,
                        chunk_index=-1,
                        content="x",
                        content_hash=a_hash("x"),
                    )
                ]
            )

    async def test_delete_by_document_clears_the_way_for_re_chunking(
        self, db_session: AsyncSession
    ) -> None:
        document = await a_document(db_session)
        repository = ChunkRepository(db_session)
        await repository.bulk_insert(
            [
                models.Chunk(
                    document_id=document.id,
                    chunk_index=index,
                    content="x",
                    content_hash=a_hash(str(index)),
                )
                for index in range(4)
            ]
        )

        removed = await repository.delete_by_document(document.id)

        assert removed == 4
        assert await repository.count_by_document(document.id) == 0


# ---------------------------------------------------------------------------
# The vector column
# ---------------------------------------------------------------------------


class TestEmbeddingColumn:
    async def test_pgvector_is_installed(self, pgvector_version: str | None) -> None:
        assert pgvector_version is not None, "the vector extension is not installed"

    async def test_column_width_matches_the_configured_model(
        self, db_session: AsyncSession
    ) -> None:
        """The width the model config implies is the width the column has.

        A mismatch here corrupts retrieval silently rather than failing, so it
        is asserted against the database's own type declaration.
        """
        declared = (
            await db_session.execute(
                text(
                    "SELECT format_type(atttypid, atttypmod) FROM pg_attribute "
                    "WHERE attrelid = 'chunks'::regclass AND attname = 'embedding'"
                )
            )
        ).scalar_one()

        assert declared == f"vector({EMBEDDING_DIMENSIONS})"

    async def test_an_embedding_round_trips(
        self, db_session: AsyncSession
    ) -> None:
        document = await a_document(db_session)
        vector = [float(i % 7) / 7 for i in range(EMBEDDING_DIMENSIONS)]
        await ChunkRepository(db_session).bulk_insert(
            [
                models.Chunk(
                    document_id=document.id,
                    chunk_index=0,
                    content="x",
                    content_hash=a_hash("x"),
                    embedding=vector,
                )
            ]
        )
        db_session.expunge_all()

        stored = (
            await ChunkRepository(db_session).list_by_document(document.id)
        )[0]

        assert stored.embedding is not None
        assert len(stored.embedding) == EMBEDDING_DIMENSIONS
        assert stored.embedding[:3] == pytest.approx(vector[:3])

    async def test_wrong_width_is_rejected(
        self, db_session: AsyncSession
    ) -> None:
        """The declared dimension is enforced, not silently coerced.

        pgvector's SQLAlchemy type checks the width while binding parameters,
        so this fails before the statement reaches the server -- which is the
        better place for it. The column type would reject it too.
        """
        document = await a_document(db_session)

        with pytest.raises(StatementError, match=f"expected {EMBEDDING_DIMENSIONS} dimensions"):
            await ChunkRepository(db_session).bulk_insert(
                [
                    models.Chunk(
                        document_id=document.id,
                        chunk_index=0,
                        content="x",
                        content_hash=a_hash("x"),
                        embedding=[0.1, 0.2, 0.3],
                    )
                ]
            )

    async def test_embedding_may_be_absent(
        self, db_session: AsyncSession
    ) -> None:
        """Chunking runs before embedding; a chunk exists in between."""
        document = await a_document(db_session)

        await ChunkRepository(db_session).bulk_insert(
            [
                models.Chunk(
                    document_id=document.id,
                    chunk_index=0,
                    content="x",
                    content_hash=a_hash("x"),
                )
            ]
        )

        stored = (await ChunkRepository(db_session).list_by_document(document.id))[0]
        assert stored.embedding is None


# ---------------------------------------------------------------------------
# Referential integrity
# ---------------------------------------------------------------------------


class TestForeignKeys:
    async def test_session_requires_a_real_user(
        self, db_session: AsyncSession
    ) -> None:
        with pytest.raises(IntegrityError):
            await SessionRepository(db_session).create(uuid.uuid4())

    async def test_message_requires_a_real_session(
        self, db_session: AsyncSession
    ) -> None:
        with pytest.raises(IntegrityError):
            await MessageRepository(db_session).create(
                session_id=uuid.uuid4(), role=ROLE_USER, content="x"
            )

    async def test_chunk_requires_a_real_document(
        self, db_session: AsyncSession
    ) -> None:
        with pytest.raises(IntegrityError):
            await ChunkRepository(db_session).bulk_insert(
                [
                    models.Chunk(
                        document_id=uuid.uuid4(),
                        chunk_index=0,
                        content="x",
                        content_hash=a_hash("x"),
                    )
                ]
            )

    async def test_deleting_a_user_cascades_to_the_whole_conversation(
        self, db_session: AsyncSession
    ) -> None:
        user = await a_user(db_session)
        conversation = await SessionRepository(db_session).create(user.id)
        await MessageRepository(db_session).create(
            session_id=conversation.id, role=ROLE_USER, content="x"
        )
        await ArtifactRepository(db_session).create(
            session_id=conversation.id,
            artifact_type=ARTIFACT_MARKDOWN,
            title="t",
            content="c",
        )

        await db_session.execute(
            text("DELETE FROM users WHERE id = :id"), {"id": user.id}
        )

        for table in ("sessions", "messages", "artifacts"):
            remaining = (
                await db_session.execute(text(f"SELECT count(*) FROM {table}"))
            ).scalar_one()
            assert remaining == 0, f"{table} should have cascaded"

    async def test_deleting_a_document_cascades_to_its_chunks(
        self, db_session: AsyncSession
    ) -> None:
        document = await a_document(db_session)
        await ChunkRepository(db_session).bulk_insert(
            [
                models.Chunk(
                    document_id=document.id,
                    chunk_index=index,
                    content="x",
                    content_hash=a_hash(str(index)),
                )
                for index in range(3)
            ]
        )

        await db_session.execute(
            text("DELETE FROM documents WHERE id = :id"), {"id": document.id}
        )

        remaining = (
            await db_session.execute(select(func.count()).select_from(models.Chunk))
        ).scalar_one()
        assert remaining == 0

    async def test_deleting_a_message_keeps_its_artifact(
        self, db_session: AsyncSession
    ) -> None:
        """SET NULL, not CASCADE: the user may still have the document open."""
        conversation = await a_session(db_session)
        message = await MessageRepository(db_session).create(
            session_id=conversation.id, role=ROLE_ASSISTANT, content="x"
        )
        artifact = await ArtifactRepository(db_session).create(
            session_id=conversation.id,
            message_id=message.id,
            artifact_type=ARTIFACT_MARKDOWN,
            title="t",
            content="c",
        )

        await db_session.execute(
            text("DELETE FROM messages WHERE id = :id"), {"id": message.id}
        )
        db_session.expunge_all()
        survivor = await ArtifactRepository(db_session).get(artifact.id)

        assert survivor is not None
        assert survivor.message_id is None

    async def test_conversations_and_transcripts_are_unrelated(
        self, db_session: AsyncSession
    ) -> None:
        """Re-ingesting the corpus must not touch anybody's conversation."""
        conversation = await a_session(db_session)
        await MessageRepository(db_session).create(
            session_id=conversation.id, role=ROLE_USER, content="keep me"
        )
        document = await a_document(db_session)

        await db_session.execute(
            text("DELETE FROM documents WHERE id = :id"), {"id": document.id}
        )

        remaining = (
            await db_session.execute(select(func.count()).select_from(models.Message))
        ).scalar_one()
        assert remaining == 1