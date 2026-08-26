"""SQLAlchemy models.

Two groups of data, deliberately unrelated: a conversation does not own
transcript rows, and re-ingesting the corpus does not touch a conversation.

    users -> sessions -> messages -> artifacts      (application)
    documents -> chunks                             (knowledge base)

`metadata` is reserved on a declarative class, so the Python attribute is
user_metadata / chunk_metadata while the column is `metadata`.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.config import get_settings
from app.constants import (
    ARTIFACT_TYPES,
    MESSAGE_ROLES,
    ArtifactType,
    MessageRole,
)
from app.db.base import Base, TimestampMixin, utcnow, uuid_pk

# The column width comes from the configured embedding model, never a literal:
# a mismatch corrupts retrieval silently rather than failing.
EMBEDDING_DIMENSIONS = get_settings().embedding_dimensions


def _in_check(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


class User(Base, TimestampMixin):
    """An anonymous user.

    No authentication in the MVP. The row exists so sessions have an owner:
    the client keeps this id and sends it back. `metadata` is the extension
    point for client-side detail, so adding one needs no migration.
    """

    __tablename__ = "users"

    id: Mapped[uuid_pk]
    user_metadata: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSONB,
        nullable=False,
        default=dict,
        server_default=func.jsonb_build_object(),
    )

    sessions: Mapped[list[Session]] = relationship(
        back_populates="user", cascade="all, delete-orphan", passive_deletes=True
    )


class Session(Base, TimestampMixin):
    """One conversation -- the context boundary for follow-up questions."""

    __tablename__ = "sessions"
    __table_args__ = (
        # The sidebar lists a user's sessions most-recently-active first.
        Index("ix_sessions_user_id_updated_at", "user_id", "updated_at"),
    )

    id: Mapped[uuid_pk]
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )

    user: Mapped[User] = relationship(back_populates="sessions")
    messages: Mapped[list[Message]] = relationship(
        back_populates="session",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="Message.created_at",
    )
    artifacts: Mapped[list[Artifact]] = relationship(
        back_populates="session", cascade="all, delete-orphan", passive_deletes=True
    )


class Message(Base):
    """One turn in a conversation.

    created_at defaults to clock_timestamp(), not now(): now() is the
    transaction start time, so a user message and the reply written in one
    transaction would share a timestamp and their order would be undefined.
    """

    __tablename__ = "messages"
    __table_args__ = (
        CheckConstraint(_in_check("role", MESSAGE_ROLES), name="message_role"),
        Index("ix_messages_session_id_created_at", "session_id", "created_at"),
    )

    id: Mapped[uuid_pk]
    session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role: Mapped[MessageRole] = mapped_column(String(16), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    # Source provenance for an assistant turn, so reopening a conversation
    # restores its citations. Holds metadata only -- never the retrieved
    # passages.
    #
    # none_as_null because SQLAlchemy otherwise stores Python None as JSON
    # 'null', leaving two different representations of "no provenance" in one
    # column and breaking `WHERE metadata IS NULL`.
    message_metadata: Mapped[dict[str, Any] | None] = mapped_column(
        "metadata", JSONB(none_as_null=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utcnow,
        server_default=func.clock_timestamp(),
    )

    session: Mapped[Session] = relationship(back_populates="messages")
    artifacts: Mapped[list[Artifact]] = relationship(back_populates="message")


class Artifact(Base, TimestampMixin):
    """A generated Markdown or HTML document shown beside the conversation.

    `content` is stored exactly as generated and treated as untrusted;
    sanitisation happens at render time, so the security decision is never
    baked into the data.

    message_id is nullable and SET NULL on delete: removing a message should
    not destroy a document the user may still have open.
    """

    __tablename__ = "artifacts"
    __table_args__ = (
        CheckConstraint(_in_check("type", ARTIFACT_TYPES), name="artifact_type"),
    )

    id: Mapped[uuid_pk]
    session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    message_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("messages.id", ondelete="SET NULL"), nullable=True, index=True
    )
    type: Mapped[ArtifactType] = mapped_column(String(16), nullable=False)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)

    session: Mapped[Session] = relationship(back_populates="artifacts")
    message: Mapped[Message | None] = relationship(back_populates="artifacts")


class Document(Base, TimestampMixin):
    """One podcast episode transcript.

    Identity is source_path -- the transcript's path in the corpus repository
    -- because that is what stays stable across re-ingests.

    content_hash makes refresh incremental: unchanged hash means skip. It is
    indexed but not unique; two episodes with identical text would be strange,
    not a constraint violation.

    title, guest and source_url are what the UI shows under an answer, so a
    retrieved chunk can be attributed without reading the transcript file.
    """

    __tablename__ = "documents"

    id: Mapped[uuid_pk]
    source_path: Mapped[str] = mapped_column(String(1024), nullable=False, unique=True)
    source_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    guest: Mapped[str | None] = mapped_column(String(256), nullable=True)
    publish_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    # Null means never fully ingested, which is how a partially failed run
    # stays distinguishable from a clean one.
    last_ingested_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    chunks: Mapped[list[Chunk]] = relationship(
        back_populates="document",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="Chunk.chunk_index",
    )


class Chunk(Base, TimestampMixin):
    """A retrievable slice of one transcript, with its embedding.

    (document_id, chunk_index) is unique: a chunk's position is part of its
    identity, and two chunks claiming position 4 of one episode would make
    provenance ambiguous.
    """

    __tablename__ = "chunks"
    __table_args__ = (
        UniqueConstraint("document_id", "chunk_index", name="uq_chunks_document_index"),
        CheckConstraint("chunk_index >= 0", name="chunk_index_non_negative"),
        # HNSW rather than IVFFlat: IVFFlat builds its lists from the rows
        # present at CREATE INDEX time, and the table is empty at migration
        # time. Cosine, matching RETRIEVAL_MAX_DISTANCE.
        Index(
            "ix_chunks_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )

    id: Mapped[uuid_pk]
    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    embedding: Mapped[list[float] | None] = mapped_column(
        Vector(EMBEDDING_DIMENSIONS), nullable=True
    )
    # Token counts, speaker, offsets -- whatever chunking records. Episode-level
    # provenance lives on the document so it cannot drift between chunks.
    chunk_metadata: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSONB,
        nullable=False,
        default=dict,
        server_default=func.jsonb_build_object(),
    )

    document: Mapped[Document] = relationship(back_populates="chunks")
