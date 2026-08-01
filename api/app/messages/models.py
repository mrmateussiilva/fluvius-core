import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.common.enums import MessageDirection, MessageStatus, MessageType
from app.common.models import TimestampMixin, UUIDPrimaryKeyMixin
from app.database import Base


class Message(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "messages"
    __table_args__ = (
        UniqueConstraint("tenant_id", "provider_message_id", name="uq_messages_provider_id"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    sender_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    sender_name: Mapped[str | None] = mapped_column(String(160))
    participant_phone: Mapped[str | None] = mapped_column(String(32))
    participant_name: Mapped[str | None] = mapped_column(String(160))
    reply_to_message_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("messages.id", ondelete="SET NULL"), index=True
    )
    direction: Mapped[MessageDirection] = mapped_column(
        Enum(
            MessageDirection,
            name="message_direction",
            values_callable=lambda e: [x.value for x in e],
        ),
        nullable=False,
    )
    message_type: Mapped[MessageType] = mapped_column(
        Enum(MessageType, name="message_type", values_callable=lambda e: [x.value for x in e]),
        nullable=False,
    )
    status: Mapped[MessageStatus] = mapped_column(
        Enum(MessageStatus, name="message_status", values_callable=lambda e: [x.value for x in e]),
        default=MessageStatus.PENDING,
        nullable=False,
        index=True,
    )
    body: Mapped[str | None] = mapped_column(Text)
    mentioned_phones: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    mentioned_jids: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    referenced_contacts: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    provider_message_id: Mapped[str | None] = mapped_column(String(255))
    reply_to_provider_message_id: Mapped[str | None] = mapped_column(String(255), index=True)
    error: Mapped[str | None] = mapped_column(Text)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    edited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    edit_content_unavailable: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )


class MessageRevision(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "message_revisions"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "provider_event_id",
            name="uq_message_revisions_provider_event",
        ),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    message_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("messages.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    provider_event_id: Mapped[str] = mapped_column(String(255), nullable=False)
    previous_body: Mapped[str | None] = mapped_column(Text)
    body: Mapped[str | None] = mapped_column(Text)
    content_available: Mapped[bool] = mapped_column(Boolean, nullable=False)
    edited_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
