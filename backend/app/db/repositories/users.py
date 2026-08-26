"""Data access for anonymous users."""

from __future__ import annotations

import uuid
from typing import Any

from app.db import models
from app.db.repositories.base import BaseRepository


class UserRepository(BaseRepository):
    async def create(
        self,
        *,
        user_id: uuid.UUID | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> models.User:
        """Create a user.

        user_id may be supplied so the client can mint its own identifier and
        keep it in browser storage -- the whole persistence mechanism for an
        anonymous user.
        """
        user = models.User(user_metadata=metadata or {})
        if user_id is not None:
            user.id = user_id
        self.session.add(user)
        await self.session.flush()
        return user

    async def get(self, user_id: uuid.UUID) -> models.User | None:
        return await self.session.get(models.User, user_id)

    async def get_or_create(self, user_id: uuid.UUID) -> models.User:
        """A returning visitor may send an id that predates a database reset."""
        existing = await self.get(user_id)
        if existing is not None:
            return existing
        return await self.create(user_id=user_id)
