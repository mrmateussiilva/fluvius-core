import uuid

from sqlalchemy import JSON, Enum, ForeignKey, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.common.enums import ChannelProvider, ChannelStatus
from app.common.models import TimestampMixin, UUIDPrimaryKeyMixin
from app.database import Base


class WhatsAppChannel(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "whatsapp_channels"
    __table_args__ = (
        UniqueConstraint(
            "provider",
            "credential_fingerprint",
            name="uq_whatsapp_channels_provider_credential",
        ),
        UniqueConstraint(
            "tenant_id",
            "provisioning_key",
            name="uq_whatsapp_channels_tenant_provisioning_key",
        ),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    phone_number: Mapped[str | None] = mapped_column(String(32))
    provider: Mapped[ChannelProvider] = mapped_column(
        Enum(
            ChannelProvider,
            name="channel_provider",
            values_callable=lambda enum: [item.value for item in enum],
        ),
        nullable=False,
    )
    status: Mapped[ChannelStatus] = mapped_column(
        Enum(
            ChannelStatus,
            name="channel_status",
            values_callable=lambda enum: [item.value for item in enum],
        ),
        default=ChannelStatus.DISCONNECTED,
        nullable=False,
        index=True,
    )
    provider_config: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    credential_fingerprint: Mapped[str | None] = mapped_column(String(64))
    provisioning_key: Mapped[uuid.UUID | None] = mapped_column(Uuid)
