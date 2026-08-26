"""message source metadata

Adds a nullable JSONB column to messages so an assistant turn can keep the
sources it was grounded in, and reopening a conversation restores its
citations. Nullable so existing rows are untouched.

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-27 00:00:00.000000+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "messages",
        sa.Column(
            "metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True
        ),
    )


def downgrade() -> None:
    op.drop_column("messages", "metadata")
