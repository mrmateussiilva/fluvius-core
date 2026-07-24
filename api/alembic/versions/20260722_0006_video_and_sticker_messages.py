"""Add video and sticker message types.

Revision ID: 20260722_0006
Revises: 20260722_0005
Create Date: 2026-07-22
"""

from alembic import op


revision = "20260722_0006"
down_revision = "20260722_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TYPE message_type ADD VALUE IF NOT EXISTS 'video'")
    op.execute("ALTER TYPE message_type ADD VALUE IF NOT EXISTS 'sticker'")


def downgrade() -> None:
    # PostgreSQL does not remove enum values safely while rows can reference them.
    pass
