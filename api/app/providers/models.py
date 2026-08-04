import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.common.models import TimestampMixin, UUIDPrimaryKeyMixin
from app.database import Base


class ProviderEvent(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "provider_events"
    __table_args__ = (
        UniqueConstraint("channel_id", "provider_event_id", name="uq_provider_events_external_id"),
        Index(
            "ix_provider_events_tenant_processed_created",
            "tenant_id",
            "processed",
            "created_at",
        ),
        Index(
            "ix_provider_events_channel_processed_created",
            "channel_id",
            "processed",
            "created_at",
        ),
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


class ProviderEventInbox(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "provider_event_inbox"
    __table_args__ = (
        UniqueConstraint(
            "provider_event_id",
            name="uq_provider_event_inbox_event_id",
        ),
        CheckConstraint(
            "status IN "
            "('queued', 'enqueued', 'processing', 'retry_wait', 'completed', 'failed')",
            name="ck_provider_event_inbox_status",
        ),
        CheckConstraint(
            "attempt_count >= 0 AND max_attempts BETWEEN 1 AND 20 "
            "AND attempt_count <= max_attempts",
            name="ck_provider_event_inbox_attempts",
        ),
        CheckConstraint(
            "normalized_kind IN ('message', 'edit')",
            name="ck_provider_event_inbox_normalized_kind",
        ),
        Index(
            "ix_provider_event_inbox_tenant_due",
            "tenant_id",
            "status",
            "next_attempt_at",
        ),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    provider_event_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("provider_events.id", ondelete="CASCADE"),
        nullable=False,
    )
    normalized_kind: Mapped[str] = mapped_column(String(24), nullable=False)
    normalized_payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(
        String(24),
        default="queued",
        nullable=False,
        index=True,
    )
    attempt_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_attempts: Mapped[int] = mapped_column(Integer, default=8, nullable=False)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rq_job_id: Mapped[str | None] = mapped_column(String(255))
    last_error: Mapped[str | None] = mapped_column(String(500))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    media_storage_key: Mapped[str | None] = mapped_column(String(500))
    media_file_name: Mapped[str | None] = mapped_column(String(255))
    media_content_type: Mapped[str | None] = mapped_column(String(120))
    media_size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    media_content_sha256: Mapped[str | None] = mapped_column(String(64))
    media_error: Mapped[str | None] = mapped_column(String(500))


class ProviderCredential(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "provider_credentials"
    __table_args__ = (
        UniqueConstraint(
            "channel_id",
            "provider",
            name="uq_provider_credentials_channel_provider",
        ),
        UniqueConstraint(
            "provider",
            "secret_fingerprint",
            name="uq_provider_credentials_provider_fingerprint",
        ),
        CheckConstraint(
            "provisioning_status IN ('pending', 'active', 'failed', 'uncertain')",
            name="ck_provider_credentials_provisioning_status",
        ),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    channel_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("whatsapp_channels.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    provider: Mapped[str] = mapped_column(String(40), nullable=False)
    encrypted_secret: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    secret_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    encryption_version: Mapped[int] = mapped_column(default=1, nullable=False)
    provisioning_status: Mapped[str] = mapped_column(
        String(24), default="pending", nullable=False, index=True
    )
    last_error: Mapped[str | None] = mapped_column(String(500))
