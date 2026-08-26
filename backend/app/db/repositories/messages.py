"""Data access for conversation messages."""

from __future__ import annotations

import uuid

from sqlalchemy import select

from app.constants import MessageRole
from app.db import models
from app.db.repositories.base import BaseRepository


class MessageRepository(BaseRepository):
    async def create(
        self, *, session_id: uuid.UUID, role: MessageRole, content: str
    ) -> models.Message:
        message = models.Message(session_id=session_id, role=role, content=content)
        self.session.add(message)
        await self.session.flush()
        return message

    async def list_by_session(self, session_id: uuid.UUID) -> list[models.Message]:
        """A conversation in the order it was written.

        Ordered by (created_at, id) so the ordering is total: without the
        tie-break, two messages sharing a timestamp could come back in either
        order and a conversation would silently reorder between reads.
        """
        result = await self.session.execute(
            select(models.Message)
            .where(models.Message.session_id == session_id)
            .order_by(models.Message.created_at, models.Message.id)
        )
        return list(result.scalars().all())
