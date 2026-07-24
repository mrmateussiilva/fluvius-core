"""Add message replies and delivery timestamps.

Revision ID: 20260722_0004
Revises: 20260722_0003
Create Date: 2026-07-22
"""

import sqlalchemy as sa
from alembic import op


revision = "20260722_0004"
down_revision = "20260722_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "messages",
        sa.Column(
            "reply_to_message_id",
            sa.Uuid(),
            sa.ForeignKey("messages.id", ondelete="SET NULL"),
        ),
    )
    op.add_column("messages", sa.Column("reply_to_provider_message_id", sa.String(255)))
    op.add_column(
        "messages",
        sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column("messages", sa.Column("last_attempt_at", sa.DateTime(timezone=True)))
    op.add_column("messages", sa.Column("sent_at", sa.DateTime(timezone=True)))
    op.add_column("messages", sa.Column("delivered_at", sa.DateTime(timezone=True)))
    op.add_column("messages", sa.Column("read_at", sa.DateTime(timezone=True)))
    op.create_index("ix_messages_reply_to_message_id", "messages", ["reply_to_message_id"])
    op.create_index(
        "ix_messages_reply_to_provider_message_id",
        "messages",
        ["reply_to_provider_message_id"],
    )
    op.execute(
        "UPDATE messages SET sent_at = created_at "
        "WHERE status NOT IN ('pending', 'failed')"
    )
    op.execute("UPDATE messages SET attempt_count = 1 WHERE direction = 'outgoing'")


def downgrade() -> None:
    op.drop_index("ix_messages_reply_to_provider_message_id", table_name="messages")
    op.drop_index("ix_messages_reply_to_message_id", table_name="messages")
    for column in (
        "read_at",
        "delivered_at",
        "sent_at",
        "last_attempt_at",
        "attempt_count",
        "reply_to_provider_message_id",
        "reply_to_message_id",
    ):
        op.drop_column("messages", column)
