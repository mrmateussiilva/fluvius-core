import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, UniqueConstraint, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.common.enums import ConversationStatus
from app.common.models import TimestampMixin, UUIDPrimaryKeyMixin
from app.database import Base


class Conversation(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "conversations"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "channel_id",
            "contact_id",
            name="uq_conversations_tenant_channel_contact",
        ),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    channel_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("whatsapp_channels.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    contact_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("contacts.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    assigned_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    status: Mapped[ConversationStatus] = mapped_column(
        Enum(
            ConversationStatus,
            name="conversation_status",
            values_callable=lambda e: [x.value for x in e],
        ),
        default=ConversationStatus.NEW,
        nullable=False,
        index=True,
    )
    last_message_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)


class ConversationRead(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "conversation_reads"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "conversation_id",
            "user_id",
            name="uq_conversation_reads_user",
        ),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    last_read_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
