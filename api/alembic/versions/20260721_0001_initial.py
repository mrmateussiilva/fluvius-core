"""Initial Fluvius Core schema.

Revision ID: 20260721_0001
Revises:
Create Date: 2026-07-21
"""

from alembic import op
import sqlalchemy as sa


revision = "20260721_0001"
down_revision = None
branch_labels = None
depends_on = None

channel_provider = sa.Enum("evolution_go", "meta_cloud", "bsp", name="channel_provider")
channel_status = sa.Enum(
    "disconnected", "connecting", "connected", "requires_qr", "failed", name="channel_status"
)
conversation_status = sa.Enum("new", "open", "closed", name="conversation_status")
message_direction = sa.Enum("incoming", "outgoing", name="message_direction")
message_type = sa.Enum("text", "image", "document", "audio", name="message_type")
message_status = sa.Enum("pending", "sent", "delivered", "read", "failed", name="message_status")


def timestamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "tenants",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("slug", sa.String(100), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        *timestamps(),
    )
    op.create_index("ix_tenants_slug", "tenants", ["slug"], unique=True)

    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        *timestamps(),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    op.create_table(
        "tenant_users",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("role", sa.String(40), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        *timestamps(),
        sa.UniqueConstraint("tenant_id", "user_id", name="uq_tenant_users_membership"),
    )
    op.create_index("ix_tenant_users_tenant_id", "tenant_users", ["tenant_id"])
    op.create_index("ix_tenant_users_user_id", "tenant_users", ["user_id"])

    op.create_table(
        "whatsapp_channels",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("phone_number", sa.String(32)),
        sa.Column("provider", channel_provider, nullable=False),
        sa.Column("status", channel_status, nullable=False),
        sa.Column("provider_config", sa.JSON(), nullable=False),
        *timestamps(),
    )
    op.create_index("ix_whatsapp_channels_tenant_id", "whatsapp_channels", ["tenant_id"])
    op.create_index("ix_whatsapp_channels_status", "whatsapp_channels", ["status"])

    op.create_table(
        "contacts",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(160)),
        sa.Column("phone_number", sa.String(32), nullable=False),
        *timestamps(),
        sa.UniqueConstraint("tenant_id", "phone_number", name="uq_contacts_tenant_phone"),
    )
    op.create_index("ix_contacts_tenant_id", "contacts", ["tenant_id"])

    op.create_table(
        "conversations",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("channel_id", sa.Uuid(), sa.ForeignKey("whatsapp_channels.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("contact_id", sa.Uuid(), sa.ForeignKey("contacts.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("assigned_user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("status", conversation_status, nullable=False),
        sa.Column("last_message_at", sa.DateTime(timezone=True)),
        *timestamps(),
    )
    for column in ("tenant_id", "channel_id", "contact_id", "assigned_user_id", "status", "last_message_at"):
        op.create_index(f"ix_conversations_{column}", "conversations", [column])

    op.create_table(
        "messages",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("conversation_id", sa.Uuid(), sa.ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("sender_user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("direction", message_direction, nullable=False),
        sa.Column("message_type", message_type, nullable=False),
        sa.Column("status", message_status, nullable=False),
        sa.Column("body", sa.Text()),
        sa.Column("provider_message_id", sa.String(255)),
        sa.Column("error", sa.Text()),
        *timestamps(),
        sa.UniqueConstraint("tenant_id", "provider_message_id", name="uq_messages_provider_id"),
    )
    for column in ("tenant_id", "conversation_id", "sender_user_id", "status"):
        op.create_index(f"ix_messages_{column}", "messages", [column])

    op.create_table(
        "message_attachments",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("message_id", sa.Uuid(), sa.ForeignKey("messages.id", ondelete="CASCADE"), nullable=False),
        sa.Column("file_name", sa.String(255), nullable=False),
        sa.Column("content_type", sa.String(120), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("storage_key", sa.String(500), nullable=False),
        sa.Column("public_url", sa.String(1000), nullable=False),
        *timestamps(),
    )
    op.create_index("ix_message_attachments_tenant_id", "message_attachments", ["tenant_id"])
    op.create_index("ix_message_attachments_message_id", "message_attachments", ["message_id"])

    op.create_table(
        "quick_replies",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_by_user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("shortcut", sa.String(80), nullable=False),
        sa.Column("title", sa.String(160), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        *timestamps(),
        sa.UniqueConstraint("tenant_id", "shortcut", name="uq_quick_replies_shortcut"),
    )
    op.create_index("ix_quick_replies_tenant_id", "quick_replies", ["tenant_id"])

    op.create_table(
        "provider_events",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("channel_id", sa.Uuid(), sa.ForeignKey("whatsapp_channels.id", ondelete="CASCADE"), nullable=False),
        sa.Column("provider", sa.String(40), nullable=False),
        sa.Column("event_type", sa.String(120), nullable=False),
        sa.Column("provider_event_id", sa.String(255)),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("processed", sa.Boolean(), nullable=False),
        sa.Column("processing_error", sa.String(1000)),
        *timestamps(),
        sa.UniqueConstraint("channel_id", "provider_event_id", name="uq_provider_events_external_id"),
    )
    for column in ("tenant_id", "channel_id", "event_type"):
        op.create_index(f"ix_provider_events_{column}", "provider_events", [column])

    op.create_table(
        "audit_logs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("action", sa.String(120), nullable=False),
        sa.Column("entity_type", sa.String(80), nullable=False),
        sa.Column("entity_id", sa.Uuid()),
        sa.Column("metadata", sa.JSON(), nullable=False),
        *timestamps(),
    )
    for column in ("tenant_id", "user_id", "action"):
        op.create_index(f"ix_audit_logs_{column}", "audit_logs", [column])


def downgrade() -> None:
    for table in (
        "audit_logs",
        "provider_events",
        "quick_replies",
        "message_attachments",
        "messages",
        "conversations",
        "contacts",
        "whatsapp_channels",
        "tenant_users",
        "users",
        "tenants",
    ):
        op.drop_table(table)
    bind = op.get_bind()
    for enum in (
        message_status,
        message_type,
        message_direction,
        conversation_status,
        channel_status,
        channel_provider,
    ):
        enum.drop(bind, checkfirst=True)
