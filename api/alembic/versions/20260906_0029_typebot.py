"""Typebot channel configuration, sessions and durable turn claims.

Revision ID: 20260906_0029
Revises: 20260824_0028
"""

import sqlalchemy as sa

from alembic import op

revision = "20260906_0029"
down_revision = "20260824_0028"
branch_labels = None
depends_on = None


def _identity():
    return [
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    ]


def upgrade() -> None:
    # Additive only: preserve all native AI configuration and existing conversations.
    op.create_table(
        "channel_typebot_configs",
        *_identity(),
        sa.Column(
            "channel_id",
            sa.Uuid(),
            sa.ForeignKey("whatsapp_channels.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("is_enabled", sa.Boolean(), nullable=False),
        sa.Column("public_id", sa.String(255), nullable=False),
        sa.UniqueConstraint("tenant_id", "channel_id", name="uq_typebot_config_channel"),
    )
    op.create_table(
        "bot_sessions",
        *_identity(),
        sa.Column(
            "conversation_id",
            sa.Uuid(),
            sa.ForeignKey("conversations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("engine", sa.String(32), nullable=False),
        sa.Column("public_id", sa.String(255), nullable=False),
        sa.Column("external_session_id", sa.String(255)),
        sa.Column("result_id", sa.String(255)),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("status IN ('active', 'ended', 'failed')", name="ck_bot_session_status"),
        sa.CheckConstraint("engine = 'typebot'", name="ck_bot_session_engine"),
    )
    op.create_index(
        "uq_bot_session_active",
        "bot_sessions",
        ["tenant_id", "conversation_id"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )
    op.create_table(
        "bot_turns",
        *_identity(),
        sa.Column(
            "session_id",
            sa.Uuid(),
            sa.ForeignKey("bot_sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "message_id",
            sa.Uuid(),
            sa.ForeignKey("messages.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("status", sa.String(24), nullable=False),
        sa.UniqueConstraint("tenant_id", "message_id", name="uq_bot_turn_message"),
        sa.CheckConstraint(
            "status IN ('queued', 'processing', 'completed', 'discarded', 'failed')",
            name="ck_bot_turn_status",
        ),
    )
    for table, columns in (
        ("channel_typebot_configs", ("tenant_id", "channel_id")),
        ("bot_sessions", ("tenant_id", "conversation_id")),
        ("bot_turns", ("tenant_id", "session_id")),
    ):
        for column in columns:
            op.create_index(f"ix_{table}_{column}", table, [column])


def downgrade() -> None:
    op.drop_table("bot_turns")
    op.drop_table("bot_sessions")
    op.drop_table("channel_typebot_configs")
