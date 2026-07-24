"""Add per-user conversation read markers.

Revision ID: 20260722_0002
Revises: 20260721_0001
Create Date: 2026-07-22
"""

from alembic import op
import sqlalchemy as sa


revision = "20260722_0002"
down_revision = "20260721_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "conversation_reads",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "tenant_id",
            sa.Uuid(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "conversation_id",
            sa.Uuid(),
            sa.ForeignKey("conversations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "last_read_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "conversation_id",
            "user_id",
            name="uq_conversation_reads_user",
        ),
    )
    op.create_index(
        "ix_conversation_reads_tenant_id", "conversation_reads", ["tenant_id"]
    )
    op.create_index(
        "ix_conversation_reads_conversation_id",
        "conversation_reads",
        ["conversation_id"],
    )
    op.create_index("ix_conversation_reads_user_id", "conversation_reads", ["user_id"])


def downgrade() -> None:
    op.drop_table("conversation_reads")
