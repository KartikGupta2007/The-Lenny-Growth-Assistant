"""Data access for conversation sessions."""

from __future__ import annotations

import uuid

from sqlalchemy import select, update

from app.db import models
from app.db.base import utcnow
from app.db.repositories.base import BaseRepository


class SessionRepository(BaseRepository):
    async def create(self, user_id: uuid.UUID) -> models.Session:
        conversation = models.Session(user_id=user_id)
        self.session.add(conversation)
        await self.session.flush()
        return conversation

    async def get(self, session_id: uuid.UUID) -> models.Session | None:
        return await self.session.get(models.Session, session_id)

    async def list_by_user(
        self, user_id: uuid.UUID, *, limit: int | None = None
    ) -> list[models.Session]:
        """A user's conversations, most recently active first."""
        statement = (
            select(models.Session)
            .where(models.Session.user_id == user_id)
            .order_by(models.Session.updated_at.desc(), models.Session.id)
        )
        if limit is not None:
            statement = statement.limit(limit)
        result = await self.session.execute(statement)
        return list(result.scalars().all())

    async def touch(self, session_id: uuid.UUID) -> None:
        """Mark a conversation as just active.

        An explicit UPDATE, because the ORM's onupdate only fires when some
        other column changed -- adding a message would otherwise leave
        updated_at stale and break the sidebar's ordering.
        """
        await self.session.execute(
            update(models.Session)
            .where(models.Session.id == session_id)
            .values(updated_at=utcnow())
        )
