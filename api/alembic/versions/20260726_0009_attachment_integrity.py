"""add attachment integrity metadata

Revision ID: 20260726_0009
Revises: 20260726_0008
Create Date: 2026-07-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260726_0009"
down_revision: str | None = "20260726_0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "message_attachments",
        sa.Column("content_sha256", sa.String(length=64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("message_attachments", "content_sha256")
