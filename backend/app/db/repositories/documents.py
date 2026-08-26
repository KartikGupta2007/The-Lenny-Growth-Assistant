"""Data access for transcript documents.

Storage and lookup only. Downloading, parsing and cleaning transcripts is
ingestion and lives elsewhere.
"""

from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import select

from app.db import models
from app.db.base import utcnow
from app.db.repositories.base import BaseRepository


class DocumentRepository(BaseRepository):
    async def get(self, document_id: uuid.UUID) -> models.Document | None:
        return await self.session.get(models.Document, document_id)

    async def get_by_source_path(self, source_path: str) -> models.Document | None:
        """source_path is a transcript's stable identity across re-ingests."""
        result = await self.session.execute(
            select(models.Document).where(models.Document.source_path == source_path)
        )
        return result.scalar_one_or_none()

    async def list_by_content_hash(self, content_hash: str) -> list[models.Document]:
        """A list, not one row: identical text under two paths is allowed."""
        result = await self.session.execute(
            select(models.Document).where(models.Document.content_hash == content_hash)
        )
        return list(result.scalars().all())

    async def create(
        self,
        *,
        source_path: str,
        title: str,
        content_hash: str,
        source_url: str | None = None,
        guest: str | None = None,
        publish_date: date | None = None,
    ) -> models.Document:
        document = models.Document(
            source_path=source_path,
            title=title,
            content_hash=content_hash,
            source_url=source_url,
            guest=guest,
            publish_date=publish_date,
        )
        self.session.add(document)
        await self.session.flush()
        return document

    async def upsert(
        self,
        *,
        source_path: str,
        title: str,
        content_hash: str,
        source_url: str | None = None,
        guest: str | None = None,
        publish_date: date | None = None,
    ) -> tuple[models.Document, bool]:
        """Insert or update the document at source_path.

        Returns (document, changed). `changed` is True when the row was created
        or its content hash moved -- the signal ingestion uses to decide
        whether to re-chunk and re-embed.
        """
        existing = await self.get_by_source_path(source_path)
        if existing is None:
            created = await self.create(
                source_path=source_path,
                title=title,
                content_hash=content_hash,
                source_url=source_url,
                guest=guest,
                publish_date=publish_date,
            )
            return created, True

        changed = existing.content_hash != content_hash
        existing.title = title
        existing.content_hash = content_hash
        existing.source_url = source_url
        existing.guest = guest
        existing.publish_date = publish_date
        await self.session.flush()
        return existing, changed

    async def mark_ingested(self, document_id: uuid.UUID) -> None:
        document = await self.get(document_id)
        if document is not None:
            document.last_ingested_at = utcnow()
            await self.session.flush()
