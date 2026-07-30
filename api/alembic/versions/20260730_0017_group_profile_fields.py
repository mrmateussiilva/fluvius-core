"""store imported WhatsApp group profile fields

Revision ID: 20260730_0017
Revises: 20260730_0016
Create Date: 2026-07-30
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "20260730_0017"
down_revision: str | None = "20260730_0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "contacts",
        sa.Column("group_member_count", sa.Integer(), nullable=True),
    )
    op.add_column(
        "contacts",
        sa.Column(
            "group_members",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("contacts", "group_members")
    op.drop_column("contacts", "group_member_count")
