import uuid

from sqlalchemy import (
    Boolean,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.common.models import TimestampMixin, UUIDPrimaryKeyMixin
from app.database import Base


class ChannelAiConfig(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "channel_ai_configs"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "channel_id",
            name="uq_channel_ai_configs_tenant_channel",
        ),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    channel_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("whatsapp_channels.id", ondelete="CASCADE"), nullable=False, index=True
    )
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    provider: Mapped[str] = mapped_column(String(32), default="openai", nullable=False)
    model_name: Mapped[str] = mapped_column(String(64), default="gpt-4o-mini", nullable=False)
    api_key_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    system_prompt: Mapped[str] = mapped_column(
        Text,
        default="Você é o assistente virtual de atendimento. Responda com cordialidade, clareza e precisão.",
        nullable=False,
    )
    bot_name: Mapped[str] = mapped_column(String(64), default="IA Assistente", nullable=False)
    handoff_prompt: Mapped[str] = mapped_column(
        Text,
        default="Transfira para um atendente humano se o cliente solicitar ou se a dúvida estiver fora do escopo.",
        nullable=False,
    )
    temperature: Mapped[float] = mapped_column(Float, default=0.3, nullable=False)
    max_tokens: Mapped[int] = mapped_column(Integer, default=500, nullable=False)
