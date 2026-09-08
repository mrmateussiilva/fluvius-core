from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.models import ChannelAiConfig
from app.auth.dependencies import AuthContext, get_auth_context
from app.bots.configuration import end_channel_sessions, get_typebot_config
from app.bots.models import ChannelTypebotConfig
from app.bots.typebot.client import PUBLIC_ID_PATTERN, TypebotClient, TypebotError
from app.channels.models import WhatsAppChannel
from app.config import settings
from app.database import get_db

router = APIRouter(tags=["bots"])
Db = Annotated[Session, Depends(get_db)]
Auth = Annotated[AuthContext, Depends(get_auth_context)]


class TypebotConfigWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")
    engine: Literal["typebot"] = "typebot"
    is_enabled: bool = False
    public_id: str = Field(pattern=PUBLIC_ID_PATTERN, max_length=255)


class TypebotConfigRead(BaseModel):
    channel_id: UUID
    engine: Literal["typebot"] = "typebot"
    is_enabled: bool
    public_id: str | None


def _channel(db: Session, context: AuthContext, channel_id: UUID, *, lock=False):
    if context.membership.role != "admin":
        raise HTTPException(403, "Apenas administradores podem configurar o Typebot.")
    query = select(WhatsAppChannel).where(
        WhatsAppChannel.tenant_id == context.tenant_id,
        WhatsAppChannel.id == channel_id,
    )
    channel = db.scalar(query.with_for_update() if lock else query)
    if channel is None:
        raise HTTPException(404, "Canal não encontrado.")
    return channel


@router.get("/channels/{channel_id}/typebot-config")
def read_typebot_config(channel_id: UUID, db: Db, context: Auth) -> TypebotConfigRead:
    _channel(db, context, channel_id)
    config = get_typebot_config(db, context.tenant_id, channel_id)
    return TypebotConfigRead(
        channel_id=channel_id,
        is_enabled=bool(config and config.is_enabled),
        public_id=config.public_id if config else None,
    )


@router.put("/channels/{channel_id}/typebot-config")
def write_typebot_config(
    channel_id: UUID, payload: TypebotConfigWrite, db: Db, context: Auth
) -> TypebotConfigRead:
    _channel(db, context, channel_id, lock=True)
    if payload.is_enabled:
        try:
            TypebotClient(settings.typebot_base_url)
        except TypebotError:
            raise HTTPException(
                409, "Configure TYPEBOT_BASE_URL no ambiente da instalação."
            ) from None
        ai = db.scalar(
            select(ChannelAiConfig).where(
                ChannelAiConfig.tenant_id == context.tenant_id,
                ChannelAiConfig.channel_id == channel_id,
            )
        )
        if ai and ai.is_enabled:
            raise HTTPException(409, "Desative o Agente de IA antes de ativar Typebot.")
    config = get_typebot_config(db, context.tenant_id, channel_id)
    if config is None:
        config = ChannelTypebotConfig(tenant_id=context.tenant_id, channel_id=channel_id)
        db.add(config)
    elif config.public_id != payload.public_id or config.is_enabled != payload.is_enabled:
        end_channel_sessions(db, context.tenant_id, channel_id)
    config.public_id = payload.public_id
    config.is_enabled = payload.is_enabled
    db.commit()
    return TypebotConfigRead(
        channel_id=channel_id, is_enabled=config.is_enabled, public_id=config.public_id
    )
