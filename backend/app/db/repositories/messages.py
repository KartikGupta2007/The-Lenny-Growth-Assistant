"""Data access for conversation messages."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select

from app.constants import MessageRole
from app.db import models
from app.db.repositories.base import BaseRepository


class MessageRepository(BaseRepository):
    async def create(
        self,
        *,
        session_id: uuid.UUID,
        role: MessageRole,
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> models.Message:
        message = models.Message(
            session_id=session_id,
            role=role,
            content=content,
            message_metadata=metadata,
        )
        self.session.add(message)
        await self.session.flush()
        return message

    async def list_by_session(
        self, session_id: uuid.UUID, *, limit: int | None = None
    ) -> list[models.Message]:
        """A conversation in the order it was written.

        Ordered by (created_at, id) so the ordering is total: without the
        tie-break, two messages sharing a timestamp could come back in either
        order and a conversation would silently reorder between reads.

        `limit` returns the most recent N, still oldest-first -- what a
        follow-up needs, without loading a long conversation to slice it.
        """
        order = (models.Message.created_at, models.Message.id)
        statement = select(models.Message).where(
            models.Message.session_id == session_id
        )
        if limit is not None:
            statement = statement.order_by(*(c.desc() for c in order)).limit(limit)
            result = await self.session.execute(statement)
            return list(reversed(result.scalars().all()))
        result = await self.session.execute(statement.order_by(*order))
        return list(result.scalars().all())
