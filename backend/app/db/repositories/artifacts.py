"""Data access for generated artifacts."""

from __future__ import annotations

import uuid

from sqlalchemy import select

from app.constants import ArtifactType
from app.db import models
from app.db.repositories.base import BaseRepository


class ArtifactRepository(BaseRepository):
    async def create(
        self,
        *,
        session_id: uuid.UUID,
        artifact_type: ArtifactType,
        title: str,
        content: str,
        message_id: uuid.UUID | None = None,
    ) -> models.Artifact:
        """Store an artifact exactly as generated; sanitisation is a rendering
        concern, so the row stays the raw output."""
        artifact = models.Artifact(
            session_id=session_id,
            message_id=message_id,
            type=artifact_type,
            title=title,
            content=content,
        )
        self.session.add(artifact)
        await self.session.flush()
        return artifact

    async def get(self, artifact_id: uuid.UUID) -> models.Artifact | None:
        return await self.session.get(models.Artifact, artifact_id)

    async def list_by_session(self, session_id: uuid.UUID) -> list[models.Artifact]:
        result = await self.session.execute(
            select(models.Artifact)
            .where(models.Artifact.session_id == session_id)
            .order_by(models.Artifact.created_at.desc(), models.Artifact.id)
        )
        return list(result.scalars().all())
