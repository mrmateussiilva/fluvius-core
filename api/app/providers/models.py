import uuid

from sqlalchemy import ForeignKey, JSON, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.common.models import TimestampMixin, UUIDPrimaryKeyMixin
from app.database import Base


class ProviderEvent(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "provider_events"
    __table_args__ = (
        UniqueConstraint("channel_id", "provider_event_id", name="uq_provider_events_external_id"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    channel_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("whatsapp_channels.id", ondelete="CASCADE"), nullable=False, index=True
    )
    provider: Mapped[str] = mapped_column(String(40), nullable=False)
    event_type: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    provider_event_id: Mapped[str | None] = mapped_column(String(255))
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    processed: Mapped[bool] = mapped_column(default=False, nullable=False)
    processing_error: Mapped[str | None] = mapped_column(String(1000))
