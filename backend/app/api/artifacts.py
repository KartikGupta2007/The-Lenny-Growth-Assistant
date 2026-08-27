"""Artifacts.

    POST /api/artifacts        store an artifact in one of your conversations
    GET  /api/artifacts/{id}   read one back

HTML content is sanitised on the way in, so what is stored is already safe --
nothing depends on a caller having sanitised it first.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.sessions import current_user_id
from app.artifacts import sanitize_html
from app.constants import ARTIFACT_HTML, ROUTE_ARTIFACTS, ArtifactType
from app.db.repositories import ArtifactRepository, SessionRepository
from app.db.session import get_session
from app.errors import NotFoundError

router = APIRouter(tags=["artifacts"])

MAX_ARTIFACT_LENGTH = 200_000


class CreateArtifactRequest(BaseModel):
    session_id: uuid.UUID
    type: ArtifactType
    title: str = Field(min_length=1, max_length=512)
    content: str = Field(min_length=1, max_length=MAX_ARTIFACT_LENGTH)
    message_id: uuid.UUID | None = None


class ArtifactResponse(BaseModel):
    id: uuid.UUID
    session_id: uuid.UUID
    message_id: uuid.UUID | None
    type: ArtifactType
    title: str
    content: str
    created_at: datetime
    updated_at: datetime


async def _owned_session(
    session: AsyncSession, session_id: uuid.UUID, user_id: uuid.UUID
) -> None:
    conversation = await SessionRepository(session).get(session_id)
    if conversation is None or conversation.user_id != user_id:
        raise NotFoundError("That conversation does not exist.")


@router.post(ROUTE_ARTIFACTS, response_model=ArtifactResponse, status_code=201)
async def create_artifact(
    request: CreateArtifactRequest,
    user_id: uuid.UUID = Depends(current_user_id),
    session: AsyncSession = Depends(get_session),
) -> ArtifactResponse:
    """Store an artifact. HTML is sanitised before it is written."""
    await _owned_session(session, request.session_id, user_id)

    content = (
        sanitize_html(request.content)
        if request.type == ARTIFACT_HTML
        else request.content
    )
    artifact = await ArtifactRepository(session).create(
        session_id=request.session_id,
        message_id=request.message_id,
        artifact_type=request.type,
        title=request.title,
        content=content,
    )
    return ArtifactResponse.model_validate(artifact, from_attributes=True)


@router.get(f"{ROUTE_ARTIFACTS}/{{artifact_id}}", response_model=ArtifactResponse)
async def get_artifact(
    artifact_id: uuid.UUID,
    user_id: uuid.UUID = Depends(current_user_id),
    session: AsyncSession = Depends(get_session),
) -> ArtifactResponse:
    """Read an artifact from one of your own conversations."""
    artifact = await ArtifactRepository(session).get(artifact_id)
    if artifact is None:
        raise NotFoundError("That artifact does not exist.")
    # Another user's artifact is reported missing, as elsewhere.
    await _owned_session(session, artifact.session_id, user_id)
    return ArtifactResponse.model_validate(artifact, from_attributes=True)
