"""channel ai config and conversation bot handoff fields

Revision ID: 20260823_0027
Revises: 20260804_0026
Create Date: 2026-08-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260823_0027"
down_revision: str | None = "20260804_0026"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. Create channel_ai_configs table
    op.create_table(
        "channel_ai_configs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("channel_id", sa.Uuid(), nullable=False),
        sa.Column("is_enabled", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("provider", sa.String(length=32), server_default="openai", nullable=False),
        sa.Column("model_name", sa.String(length=64), server_default="gpt-4o-mini", nullable=False),
        sa.Column("api_key_encrypted", sa.Text(), nullable=True),
        sa.Column(
            "system_prompt",
            sa.Text(),
            server_default="Você é o assistente virtual de atendimento da empresa. Responda com cordialidade, clareza e precisão.",
            nullable=False,
        ),
        sa.Column("bot_name", sa.String(length=64), server_default="IA Assistente", nullable=False),
        sa.Column(
            "handoff_prompt",
            sa.Text(),
            server_default="Transfira para um atendente humano se o cliente solicitar ou se a dúvida estiver fora do escopo.",
            nullable=False,
        ),
        sa.Column("temperature", sa.Float(), server_default=sa.text("0.3"), nullable=False),
        sa.Column("max_tokens", sa.Integer(), server_default=sa.text("500"), nullable=False),
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
        sa.ForeignKeyConstraint(
            ["channel_id"],
            ["whatsapp_channels.id"],
            name="fk_channel_ai_configs_channel_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="fk_channel_ai_configs_tenant_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_channel_ai_configs"),
        sa.UniqueConstraint(
            "tenant_id",
            "channel_id",
            name="uq_channel_ai_configs_tenant_channel",
        ),
    )
    op.create_index(
        "ix_channel_ai_configs_channel_id",
        "channel_ai_configs",
        ["channel_id"],
        unique=False,
    )
    op.create_index(
        "ix_channel_ai_configs_tenant_id",
        "channel_ai_configs",
        ["tenant_id"],
        unique=False,
    )

    # 2. Add bot handoff fields to conversations
    op.add_column(
        "conversations",
        sa.Column(
            "is_bot_active",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
    )
    op.add_column(
        "conversations",
        sa.Column(
            "bot_handoff_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.add_column(
        "conversations",
        sa.Column(
            "bot_handoff_reason",
            sa.String(length=255),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_conversations_is_bot_active",
        "conversations",
        ["is_bot_active"],
        unique=False,
    )

    # 3. Add is_bot flag to messages
    op.add_column(
        "messages",
        sa.Column(
            "is_bot",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("messages", "is_bot")
    op.drop_index("ix_conversations_is_bot_active", table_name="conversations")
    op.drop_column("conversations", "bot_handoff_reason")
    op.drop_column("conversations", "bot_handoff_at")
    op.drop_column("conversations", "is_bot_active")
    op.drop_index("ix_channel_ai_configs_tenant_id", table_name="channel_ai_configs")
    op.drop_index("ix_channel_ai_configs_channel_id", table_name="channel_ai_configs")
    op.drop_table("channel_ai_configs")
