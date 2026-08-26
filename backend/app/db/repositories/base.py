"""Shared repository behaviour.

Repositories build all SQL; route handlers call them and never write a query.

They do not own transactions -- app.db.session.get_session commits on success
and rolls back on failure, so a handler can call several repositories and get
one atomic unit of work. Repositories only flush, and only when they need the
database to assign something before returning.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession


class BaseRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
