"""Sessions and messages.

    POST /api/sessions                        start a conversation
    GET  /api/sessions                        list this user's conversations
    GET  /api/sessions/{id}                   a conversation and its messages
    POST /api/sessions/{id}/messages          ask a question, get a grounded answer

There is no authentication, by design (PRD section 5.2). A client sends its own
identifier in `X-User-Id` and keeps it in browser storage; requests without one
share a single anonymous user. The header is trusted as-is -- it identifies, it
does not authenticate, and it must not be treated as a security boundary.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Header, Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent import answer_in_conversation
from app.constants import ArtifactType, LLMProviderId, MessageRole, ROUTE_SESSIONS
from app.db.repositories import (
    ArtifactRepository,
    MessageRepository,
    SessionRepository,
    UserRepository,
)
from app.db.session import get_session, get_sessionmaker
from app.errors import NotFoundError

router = APIRouter(tags=["sessions"])

# A question longer than this is not a question; it also keeps a runaway paste
# out of the embedding provider.
MAX_MESSAGE_LENGTH = 2000

# Conversations from a client that sends no X-User-Id all belong here.
ANONYMOUS_USER_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")


async def current_user_id(
    session: AsyncSession = Depends(get_session),
    x_user_id: uuid.UUID | None = Header(default=None),
) -> uuid.UUID:
    """Resolve the caller's user, creating the row on first sight.

    An id from browser storage may predate a database reset, so "unknown id"
    is an ordinary case rather than an error.
    """
    user_id = x_user_id or ANONYMOUS_USER_ID
    await UserRepository(session).get_or_create(user_id)
    return user_id


class SessionResponse(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    created_at: datetime
    updated_at: datetime


class SourceResponse(BaseModel):
    """A citation. Every field comes from the database, never from the model."""

    number: int
    document_id: uuid.UUID
    chunk_id: uuid.UUID
    title: str
    guest: str | None
    source_url: str | None
    chunk_index: int


class MessageResponse(BaseModel):
    id: uuid.UUID
    role: MessageRole
    content: str
    created_at: datetime
    # Populated for assistant turns. `grounded`/`provider` are None on user
    # turns and on messages written before provenance was persisted.
    sources: list[SourceResponse] = []
    grounded: bool | None = None
    provider: LLMProviderId | None = None

    @classmethod
    def of(cls, message) -> MessageResponse:  # type: ignore[no-untyped-def]
        stored = message.message_metadata or {}
        return cls(
            id=message.id,
            role=message.role,
            content=message.content,
            created_at=message.created_at,
            sources=[SourceResponse(**s) for s in stored.get("sources", [])],
            grounded=stored.get("grounded"),
            provider=stored.get("provider"),
        )


class ArtifactSummary(BaseModel):
    """Enough to list artifacts and fetch one; content comes from GET."""

    id: uuid.UUID
    message_id: uuid.UUID | None
    type: ArtifactType
    title: str
    created_at: datetime


class SessionDetailResponse(SessionResponse):
    messages: list[MessageResponse]
    artifacts: list[ArtifactSummary]


class SendMessageRequest(BaseModel):
    message: str = Field(min_length=1, max_length=MAX_MESSAGE_LENGTH)
    # Omitted means "use the configured default". An unknown id is rejected
    # here by the Literal rather than reaching the registry.
    provider: LLMProviderId | None = None

    @field_validator("message")
    @classmethod
    def _not_only_whitespace(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("message must not be empty")
        return stripped


class SendMessageResponse(BaseModel):
    message: MessageResponse
    sources: list[SourceResponse]
    # False when the corpus could not support an answer; sources is then empty.
    grounded: bool
    provider: LLMProviderId | None


@router.post(ROUTE_SESSIONS, response_model=SessionResponse, status_code=201)
async def create_session(
    user_id: uuid.UUID = Depends(current_user_id),
    session: AsyncSession = Depends(get_session),
) -> SessionResponse:
    """Start a conversation."""
    conversation = await SessionRepository(session).create(user_id)
    return SessionResponse.model_validate(conversation, from_attributes=True)


@router.get(ROUTE_SESSIONS, response_model=list[SessionResponse])
async def list_sessions(
    user_id: uuid.UUID = Depends(current_user_id),
    session: AsyncSession = Depends(get_session),
) -> list[SessionResponse]:
    """This user's conversations, most recently active first."""
    conversations = await SessionRepository(session).list_by_user(user_id)
    return [
        SessionResponse.model_validate(c, from_attributes=True) for c in conversations
    ]


@router.get(f"{ROUTE_SESSIONS}/{{session_id}}", response_model=SessionDetailResponse)
async def get_session_detail(
    session_id: uuid.UUID,
    user_id: uuid.UUID = Depends(current_user_id),
    session: AsyncSession = Depends(get_session),
) -> SessionDetailResponse:
    """A conversation and its messages, oldest first."""
    conversation = await SessionRepository(session).get(session_id)
    # Another user's conversation is reported as missing rather than forbidden:
    # without authentication there is no identity to deny.
    if conversation is None or conversation.user_id != user_id:
        raise NotFoundError("That conversation does not exist.")

    messages = await MessageRepository(session).list_by_session(session_id)
    artifacts = await ArtifactRepository(session).list_by_session(session_id)
    return SessionDetailResponse(
        id=conversation.id,
        user_id=conversation.user_id,
        created_at=conversation.created_at,
        updated_at=conversation.updated_at,
        messages=[MessageResponse.of(m) for m in messages],
        artifacts=[
            ArtifactSummary.model_validate(a, from_attributes=True) for a in artifacts
        ],
    )


@router.delete(f"{ROUTE_SESSIONS}/{{session_id}}", status_code=204)
async def delete_session(
    session_id: uuid.UUID,
    user_id: uuid.UUID = Depends(current_user_id),
    session: AsyncSession = Depends(get_session),
) -> Response:
    """Delete a conversation and its messages."""
    repository = SessionRepository(session)
    conversation = await repository.get(session_id)
    if conversation is None or conversation.user_id != user_id:
        raise NotFoundError("That conversation does not exist.")

    await repository.delete(conversation)
    return Response(status_code=204)


@router.post(
    f"{ROUTE_SESSIONS}/{{session_id}}/messages", response_model=SendMessageResponse
)
async def send_message(
    session_id: uuid.UUID,
    request: SendMessageRequest,
    user_id: uuid.UUID = Depends(current_user_id),
    session: AsyncSession = Depends(get_session),
) -> SendMessageResponse:
    """Ask a question in a conversation and get a grounded answer.

    The agent manages its own short-lived sessions so no transaction is held
    while the model runs; this request's session is used only to check that the
    conversation belongs to the caller.
    """
    conversation = await SessionRepository(session).get(session_id)
    if conversation is None or conversation.user_id != user_id:
        raise NotFoundError("That conversation does not exist.")

    message, answer = await answer_in_conversation(
        get_sessionmaker(),
        session_id,
        request.message,
        provider_id=request.provider,
    )
    return SendMessageResponse(
        message=MessageResponse.of(message),
        sources=[SourceResponse(**vars(source)) for source in answer.sources],
        grounded=answer.grounded,
        provider=answer.provider,
    )
