"""Answer a question from the transcript corpus, or decline to.

    question -> retrieval -> evidence check -> grounded context -> LLM -> answer + sources

The evidence check is the anti-hallucination control: when retrieval finds too
little, the model is never called and a fixed response is returned. A model
that is not asked cannot invent an answer.

Sources come from the retrieval result, never from the model's text. The model
may reference [1]/[2]; the URLs and titles behind those numbers are the
backend's.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agent.artifact_request import detect_artifact_request
from app.agent.prompts import (
    INSUFFICIENT_EVIDENCE_ANSWER,
    SYSTEM_PROMPT,
    build_user_message,
)
from app.artifacts import sanitize_html
from app.config import Settings, get_settings
from app.db import models
from app.constants import ARTIFACT_HTML, ARTIFACT_MARKDOWN, ArtifactType
from app.db.repositories import (
    ArtifactRepository,
    MessageRepository,
    SessionRepository,
)
from app.errors import ModelError, NotFoundError
from app.logging_config import get_logger
from app.models.base import Message, ModelProvider
from app.models.registry import ProviderRegistry, get_provider_registry
from app.retrieval import RetrievalResult, RetrievedChunk, retrieve
from app.skills import generate_html_page, generate_ship30_essay

logger = get_logger(__name__)

# How many earlier turns to carry. Enough for a follow-up to make sense without
# letting a long conversation crowd out the evidence.
MAX_HISTORY_MESSAGES = 6


@dataclass(frozen=True)
class Source:
    """A citation, owned by the backend."""

    number: int
    document_id: uuid.UUID
    chunk_id: uuid.UUID
    title: str
    guest: str | None
    source_url: str | None
    chunk_index: int


@dataclass(frozen=True)
class Answer:
    answer: str
    sources: list[Source] = field(default_factory=list)
    # False when the answer is the fixed insufficient-evidence response.
    grounded: bool = True
    provider: str | None = None


def _to_sources(chunks: list[RetrievedChunk]) -> list[Source]:
    return [
        Source(
            number=number,
            document_id=chunk.document_id,
            chunk_id=chunk.chunk_id,
            title=chunk.title,
            guest=chunk.guest,
            source_url=chunk.source_url,
            chunk_index=chunk.chunk_index,
        )
        for number, chunk in enumerate(chunks, start=1)
    ]


async def answer_question(
    session: AsyncSession,
    question: str,
    *,
    history: list[Message] | None = None,
    provider_id: str | None = None,
    settings: Settings | None = None,
    registry: ProviderRegistry | None = None,
    provider: ModelProvider | None = None,
) -> Answer:
    """Retrieve evidence for `question`, then answer from it or decline.

    `history` is earlier turns of the same conversation; only the tail is sent.
    Retrieval always runs on the current question, so a follow-up is searched
    for what it actually asks rather than for the whole conversation.

    `provider_id` selects a model; None uses the configured default. An
    unavailable provider raises ProviderUnavailableError.
    """
    settings = settings or get_settings()
    result = await retrieve(session, question, settings=settings)
    return await answer_from_evidence(
        result,
        question,
        history=history,
        provider_id=provider_id,
        registry=registry,
        provider=provider,
    )


async def answer_from_evidence(
    result: RetrievalResult,
    question: str,
    *,
    history: list[Message] | None = None,
    provider_id: str | None = None,
    registry: ProviderRegistry | None = None,
    provider: ModelProvider | None = None,
) -> Answer:
    """The half that touches no database.

    Split out so a caller can close its database session before generation,
    which can take a minute on a local model.
    """
    if not result.sufficient:
        # The model is never called, so it cannot answer unsupported.
        logger.info("answer_declined", reason="insufficient_evidence")
        return Answer(
            answer=INSUFFICIENT_EVIDENCE_ANSWER,
            sources=[],
            grounded=False,
        )

    if provider is None:
        registry = registry or get_provider_registry()
        provider = await registry.require(provider_id)

    messages = list(history or [])[-MAX_HISTORY_MESSAGES:]
    messages.append(
        Message(role="user", content=build_user_message(question, result.chunks))
    )

    logger.info(
        "generation_started",
        provider=provider.id,
        model=provider.model_name,
        evidence=len(result.chunks),
        history=len(messages) - 1,
    )
    text = await provider.generate(SYSTEM_PROMPT, messages)
    logger.info("generation_completed", provider=provider.id, characters=len(text))

    return Answer(
        answer=text,
        sources=_to_sources(result.chunks),
        grounded=True,
        provider=provider.id,
    )


async def answer_in_conversation(
    session_factory: async_sessionmaker[AsyncSession],
    conversation_id: uuid.UUID,
    question: str,
    *,
    provider_id: str | None = None,
    settings: Settings | None = None,
    registry: ProviderRegistry | None = None,
    provider: ModelProvider | None = None,
) -> tuple[models.Message, Answer]:
    """Answer inside a stored conversation, persisting both turns.

    Each step gets its own short-lived session, so no database transaction is
    held while the model runs -- that can take a minute on a local model, and a
    connection sitting idle in a transaction for a minute is a connection the
    rest of the application cannot use.

        load history + save the question -> commit
        retrieve                          -> close
        generate                          (no database)
        save the answer                   -> commit

    A generation failure therefore leaves the question persisted and no
    assistant message, rather than a fabricated success.

    Returns the stored assistant message and the Answer, whose sources the API
    returns alongside it.
    """
    settings = settings or get_settings()

    async with session_factory() as session:
        conversation = await SessionRepository(session).get(conversation_id)
        if conversation is None:
            raise NotFoundError("That conversation does not exist.")

        history = _to_history(
            await MessageRepository(session).list_by_session(
                conversation_id, limit=MAX_HISTORY_MESSAGES
            )
        )
        await MessageRepository(session).create(
            session_id=conversation_id, role="user", content=question
        )
        await SessionRepository(session).touch(conversation_id)
        await session.commit()

    async with session_factory() as session:
        result = await retrieve(session, question, settings=settings)

    wanted = detect_artifact_request(question)
    if wanted is not None and result.sufficient:
        return await _answer_with_artifact(
            session_factory,
            conversation_id,
            question,
            result,
            wanted,
            provider_id=provider_id,
            registry=registry,
            provider=provider,
        )

    answer = await answer_from_evidence(
        result,
        question,
        history=history,
        provider_id=provider_id,
        registry=registry,
        provider=provider,
    )

    async with session_factory() as session:
        message = await MessageRepository(session).create(
            session_id=conversation_id,
            role="assistant",
            content=answer.answer,
            metadata=provenance(answer),
        )
        await SessionRepository(session).touch(conversation_id)
        await session.commit()

    return message, answer


async def _answer_with_artifact(
    session_factory: async_sessionmaker[AsyncSession],
    conversation_id: uuid.UUID,
    question: str,
    result: RetrievalResult,
    kind: ArtifactType,
    *,
    provider_id: str | None,
    registry: ProviderRegistry | None,
    provider: ModelProvider | None,
) -> tuple[models.Message, Answer]:
    """Generate an artifact, then persist it against the assistant message.

    The chat message is a short deterministic note; the artifact holds the
    content, so a 1,250-word essay is not duplicated into the transcript.
    """
    if provider is None:
        registry = registry or get_provider_registry()
        provider = await registry.require(provider_id)

    logger.info(
        "artifact_generation_started", kind=kind, provider=provider.id,
        evidence=len(result.chunks),
    )
    try:
        if kind == ARTIFACT_MARKDOWN:
            content = await generate_ship30_essay(provider, question, result.chunks)
            title = _title_from(content) or "Ship 30 essay"
        else:
            content = sanitize_html(
                await generate_html_page(provider, question, result.chunks)
            )
            title = "HTML artifact"
    except ModelError:
        # The model would not produce the artifact -- in practice because the
        # evidence does not really cover the topic, even though enough chunks
        # cleared the distance threshold. Decline rather than 502, and create
        # nothing.
        logger.info("artifact_declined", kind=kind)
        return await _persist_decline(session_factory, conversation_id, kind)

    sources = _to_sources(result.chunks)
    answer = Answer(
        answer=(
            f"I've written this from {len(result.chunks)} passages across "
            f"Lenny's Podcast. It's open in the panel beside this conversation."
        ),
        sources=sources,
        grounded=True,
        provider=provider.id,
    )

    async with session_factory() as session:
        message = await MessageRepository(session).create(
            session_id=conversation_id,
            role="assistant",
            content=answer.answer,
            metadata=provenance(answer),
        )
        await ArtifactRepository(session).create(
            session_id=conversation_id,
            message_id=message.id,
            artifact_type=kind,
            title=title,
            content=content,
        )
        await SessionRepository(session).touch(conversation_id)
        await session.commit()

    logger.info("artifact_generated", kind=kind, characters=len(content))
    return message, answer


async def _persist_decline(
    session_factory: async_sessionmaker[AsyncSession],
    conversation_id: uuid.UUID,
    kind: ArtifactType,
) -> tuple[models.Message, Answer]:
    """Record that the corpus could not support the requested artifact."""
    what = "essay" if kind == ARTIFACT_MARKDOWN else "page"
    answer = Answer(
        answer=(
            f"I don't have enough material in Lenny's Podcast transcripts to "
            f"write that {what} without inventing things, so I haven't."
        ),
        sources=[],
        grounded=False,
    )
    async with session_factory() as session:
        message = await MessageRepository(session).create(
            session_id=conversation_id,
            role="assistant",
            content=answer.answer,
            metadata=provenance(answer),
        )
        await SessionRepository(session).touch(conversation_id)
        await session.commit()
    return message, answer


def _title_from(markdown: str) -> str | None:
    """The essay's own first heading, for the panel header."""
    for line in markdown.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            return stripped.lstrip("#").strip()[:200] or None
    return None


def provenance(answer: Answer) -> dict[str, Any]:
    """What an assistant message stores so its citations survive a reload.

    Metadata only -- the retrieved passages stay in `chunks` rather than being
    copied into every message that cited them.
    """
    return {
        "sources": [
            {
                "number": source.number,
                "chunk_id": str(source.chunk_id),
                "document_id": str(source.document_id),
                "title": source.title,
                "guest": source.guest,
                "source_url": source.source_url,
                "chunk_index": source.chunk_index,
            }
            for source in answer.sources
        ],
        "grounded": answer.grounded,
        "provider": answer.provider,
    }


def _to_history(stored: list[models.Message]) -> list[Message]:
    """Stored rows as provider messages."""
    return [Message(role=m.role, content=m.content) for m in stored]
