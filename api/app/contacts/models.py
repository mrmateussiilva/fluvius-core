import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.common.models import TimestampMixin, UUIDPrimaryKeyMixin
from app.database import Base


class Contact(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "contacts"
    __table_args__ = (
        UniqueConstraint("tenant_id", "phone_number", name="uq_contacts_tenant_phone"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str | None] = mapped_column(String(160))
    push_name: Mapped[str | None] = mapped_column(String(160))
    business_name: Mapped[str | None] = mapped_column(String(160))
    verified_name: Mapped[str | None] = mapped_column(String(160))
    phone_number: Mapped[str] = mapped_column(String(32), nullable=False)
    about: Mapped[str | None] = mapped_column(Text)
    profile_picture_url: Mapped[str | None] = mapped_column(Text)
    is_on_whatsapp: Mapped[bool | None] = mapped_column(Boolean)
    profile_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    profile_sync_error: Mapped[str | None] = mapped_column(String(500))
