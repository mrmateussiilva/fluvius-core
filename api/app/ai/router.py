from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.models import ChannelAiConfig
from app.ai.schemas import (
    AiConfigRead,
    AiConfigUpdate,
    AiSimulateRequest,
    AiSimulateResponse,
    BotToggleRequest,
)
from app.ai.service import (
    get_or_create_ai_config,
    simulate_ai,
    update_ai_config,
)
from app.auth.dependencies import AuthContext, get_auth_context
from app.channels.models import WhatsAppChannel
from app.conversations.models import Conversation
from app.conversations.router import get_accessible_conversation
from app.database import get_db
from app.realtime.manager import realtime_manager

router = APIRouter(tags=["ai"])


def _as_ai_config_read(config: ChannelAiConfig) -> AiConfigRead:
    return AiConfigRead(
        id=config.id,
        channel_id=config.channel_id,
        is_enabled=config.is_enabled,
        provider=config.provider,
        model_name=config.model_name,
        has_api_key=bool(config.api_key_encrypted),
        system_prompt=config.system_prompt,
        bot_name=config.bot_name,
        handoff_prompt=config.handoff_prompt,
        temperature=config.temperature,
        max_tokens=config.max_tokens,
    )


@router.get(
    "/api/v1/channels/{channel_id}/ai-config",
    response_model=AiConfigRead,
)
def get_channel_ai_config(
    channel_id: UUID,
    db: Session = Depends(get_db),
    context: AuthContext = Depends(get_auth_context),
) -> AiConfigRead:
    if context.user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Apenas administradores podem visualizar as configurações do Agente de IA.",
        )

    channel = db.scalar(
        select(WhatsAppChannel).where(
            WhatsAppChannel.id == channel_id,
            WhatsAppChannel.tenant_id == context.tenant_id,
        )
    )
    if channel is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Canal não encontrado.",
        )

    config = get_or_create_ai_config(db, context.tenant_id, channel.id)
    return _as_ai_config_read(config)


@router.put(
    "/api/v1/channels/{channel_id}/ai-config",
    response_model=AiConfigRead,
)
def update_channel_ai_config(
    channel_id: UUID,
    payload: AiConfigUpdate,
    db: Session = Depends(get_db),
    context: AuthContext = Depends(get_auth_context),
) -> AiConfigRead:
    if context.user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Apenas administradores podem alterar as configurações do Agente de IA.",
        )

    channel = db.scalar(
        select(WhatsAppChannel).where(
            WhatsAppChannel.id == channel_id,
            WhatsAppChannel.tenant_id == context.tenant_id,
        )
    )
    if channel is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Canal não encontrado.",
        )

    config = update_ai_config(db, context.tenant_id, channel.id, payload)
    return _as_ai_config_read(config)


@router.post(
    "/api/v1/channels/{channel_id}/ai-simulator",
    response_model=AiSimulateResponse,
)
async def simulate_channel_ai(
    channel_id: UUID,
    payload: AiSimulateRequest,
    db: Session = Depends(get_db),
    context: AuthContext = Depends(get_auth_context),
) -> AiSimulateResponse:
    if context.user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Apenas administradores podem testar o simulador de IA.",
        )

    channel = db.scalar(
        select(WhatsAppChannel).where(
            WhatsAppChannel.id == channel_id,
            WhatsAppChannel.tenant_id == context.tenant_id,
        )
    )
    if channel is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Canal não encontrado.",
        )

    try:
        return await simulate_ai(db, context.tenant_id, channel.id, payload)
    except ValueError as err:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(err))
    except Exception as err:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Falha na comunicação com o provedor de IA: {err}",
        )


@router.post(
    "/api/v1/conversations/{conversation_id}/toggle-bot",
    response_model=dict,
)
async def toggle_conversation_bot(
    conversation_id: UUID,
    payload: BotToggleRequest,
    db: Session = Depends(get_db),
    context: AuthContext = Depends(get_auth_context),
) -> dict:
    conversation = get_accessible_conversation(
        db,
        context,
        conversation_id,
        for_update=True,
    )

    now = datetime.now(UTC)
    conversation.is_bot_active = payload.is_bot_active
    if not payload.is_bot_active:
        conversation.bot_handoff_at = now
        conversation.bot_handoff_reason = (
            payload.reason or f"Desativado por {context.user.name}"
        )
    else:
        conversation.bot_handoff_reason = None

    db.commit()
    db.refresh(conversation)

    await realtime_manager.publish_tenant(
        tenant_id=context.tenant_id,
        event="conversation:updated",
        data={
            "id": str(conversation.id),
            "status": conversation.status.value,
            "is_bot_active": conversation.is_bot_active,
            "bot_handoff_at": (
                conversation.bot_handoff_at.isoformat()
                if conversation.bot_handoff_at
                else None
            ),
            "bot_handoff_reason": conversation.bot_handoff_reason,
            "last_message_at": (
                conversation.last_message_at.isoformat()
                if conversation.last_message_at
                else None
            ),
        },
    )

    return {
        "success": True,
        "is_bot_active": conversation.is_bot_active,
        "bot_handoff_at": conversation.bot_handoff_at,
        "bot_handoff_reason": conversation.bot_handoff_reason,
    }
