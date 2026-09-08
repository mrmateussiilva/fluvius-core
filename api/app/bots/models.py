import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.common.models import TimestampMixin, UUIDPrimaryKeyMixin
from app.database import Base


class ChannelTypebotConfig(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "channel_typebot_configs"
    __table_args__ = (
        UniqueConstraint("tenant_id", "channel_id", name="uq_typebot_config_channel"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("tenants.id", ondelete="CASCADE"), index=True
    )
    channel_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("whatsapp_channels.id", ondelete="CASCADE"), index=True
    )
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    public_id: Mapped[str] = mapped_column(String(255))


class BotSession(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "bot_sessions"
    __table_args__ = (
        CheckConstraint("status IN ('active', 'ended', 'failed')", name="ck_bot_session_status"),
        CheckConstraint("engine = 'typebot'", name="ck_bot_session_engine"),
        Index(
            "uq_bot_session_active",
            "tenant_id",
            "conversation_id",
            unique=True,
            postgresql_where=text("status = 'active'"),
        ),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("tenants.id", ondelete="CASCADE"), index=True
    )
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("conversations.id", ondelete="CASCADE"), index=True
    )
    engine: Mapped[str] = mapped_column(String(32), default="typebot")
    public_id: Mapped[str] = mapped_column(String(255))
    external_session_id: Mapped[str | None] = mapped_column(String(255))
    result_id: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(24), default="active")
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class BotTurn(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Durable POST claim: an ambiguous attempt must never be replayed."""

    __tablename__ = "bot_turns"
    __table_args__ = (
        UniqueConstraint("tenant_id", "message_id", name="uq_bot_turn_message"),
        CheckConstraint(
            "status IN ('queued', 'processing', 'completed', 'discarded', 'failed')",
            name="ck_bot_turn_status",
        ),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("tenants.id", ondelete="CASCADE"), index=True
    )
    session_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("bot_sessions.id", ondelete="CASCADE"), index=True
    )
    message_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("messages.id", ondelete="CASCADE")
    )
    status: Mapped[str] = mapped_column(String(24), default="queued")
