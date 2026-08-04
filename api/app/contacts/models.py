import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.common.enums import ContactKind
from app.common.models import TimestampMixin, UUIDPrimaryKeyMixin
from app.database import Base


class Contact(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "contacts"
    __table_args__ = (
        UniqueConstraint("tenant_id", "phone_number", name="uq_contacts_tenant_phone"),
        Index("ix_contacts_tenant_kind", "tenant_id", "kind"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    kind: Mapped[ContactKind] = mapped_column(
        Enum(
            ContactKind,
            name="contact_kind",
            values_callable=lambda e: [x.value for x in e],
        ),
        default=ContactKind.DIRECT,
        nullable=False,
    )
    name: Mapped[str | None] = mapped_column(String(160))
    address_book_name: Mapped[str | None] = mapped_column(String(160))
    push_name: Mapped[str | None] = mapped_column(String(160))
    business_name: Mapped[str | None] = mapped_column(String(160))
    verified_name: Mapped[str | None] = mapped_column(String(160))
    phone_number: Mapped[str] = mapped_column(String(64), nullable=False)
    provider_address: Mapped[str | None] = mapped_column(String(255))
    about: Mapped[str | None] = mapped_column(Text)
    profile_picture_url: Mapped[str | None] = mapped_column(Text)
    is_on_whatsapp: Mapped[bool | None] = mapped_column(Boolean)
    profile_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    profile_sync_error: Mapped[str | None] = mapped_column(String(500))
    group_member_count: Mapped[int | None] = mapped_column(Integer)
    group_members: Mapped[list | None] = mapped_column(JSONB)

    @property
    def delivery_address(self) -> str:
        if self.provider_address:
            return self.provider_address
        if self.kind == ContactKind.GROUP:
            return f"{self.phone_number}@g.us"
        return self.phone_number
