from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.ai.models import ChannelAiConfig
from app.bots.models import BotSession, ChannelTypebotConfig
from app.conversations.models import Conversation


def get_typebot_config(
    db: Session,
    tenant_id: UUID,
    channel_id: UUID,
) -> ChannelTypebotConfig | None:
    return db.scalar(
        select(ChannelTypebotConfig)
        .where(
            ChannelTypebotConfig.tenant_id == tenant_id,
            ChannelTypebotConfig.channel_id == channel_id,
        )
        .execution_options(populate_existing=True)
    )


def configured_engine(db: Session, tenant_id: UUID, channel_id: UUID) -> str | None:
    # Defensive precedence for invalid configurations written outside the admin API.
    config = get_typebot_config(db, tenant_id, channel_id)
    if config and config.is_enabled:
        return "typebot"
    ai = db.scalar(
        select(ChannelAiConfig)
        .where(
            ChannelAiConfig.tenant_id == tenant_id,
            ChannelAiConfig.channel_id == channel_id,
        )
        .execution_options(populate_existing=True)
    )
    return "native_ai" if ai and ai.is_enabled else None


def end_bot_sessions(db: Session, tenant_id: UUID, conversation_id: UUID) -> None:
    db.execute(
        update(BotSession)
        .where(
            BotSession.tenant_id == tenant_id,
            BotSession.conversation_id == conversation_id,
            BotSession.status == "active",
        )
        .values(status="ended", ended_at=datetime.now(UTC))
    )


def end_channel_sessions(db: Session, tenant_id: UUID, channel_id: UUID) -> None:
    conversations = select(Conversation.id).where(
        Conversation.tenant_id == tenant_id,
        Conversation.channel_id == channel_id,
    )
    db.execute(
        update(BotSession)
        .where(
            BotSession.tenant_id == tenant_id,
            BotSession.conversation_id.in_(conversations),
            BotSession.status == "active",
        )
        .values(status="ended", ended_at=datetime.now(UTC))
    )
