import uuid

from sqlalchemy import Enum, ForeignKey, JSON, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.common.enums import ChannelProvider, ChannelStatus
from app.common.models import TimestampMixin, UUIDPrimaryKeyMixin
from app.database import Base


class WhatsAppChannel(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "whatsapp_channels"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    phone_number: Mapped[str | None] = mapped_column(String(32))
    provider: Mapped[ChannelProvider] = mapped_column(
        Enum(ChannelProvider, name="channel_provider", values_callable=lambda e: [x.value for x in e]),
        nullable=False,
    )
    status: Mapped[ChannelStatus] = mapped_column(
        Enum(ChannelStatus, name="channel_status", values_callable=lambda e: [x.value for x in e]),
        default=ChannelStatus.DISCONNECTED,
        nullable=False,
        index=True,
    )
    provider_config: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
