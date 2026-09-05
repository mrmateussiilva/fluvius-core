import logging
from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.models import ChannelAiConfig
from app.ai.schemas import (
    AiConfigRead,
    AiConfigUpdate,
    AiConversationAnalysisResponse,
    AiSimulateRequest,
    AiSimulateResponse,
    AiSummaryResponse,
    BotToggleRequest,
)
from app.ai.service import (
    get_or_create_ai_config,
    analyze_conversation_history,
    simulate_ai,
    summarize_conversation_history,
    update_ai_config,
)
from app.auth.dependencies import AuthContext, get_auth_context
from app.channels.models import WhatsAppChannel
from app.conversations.router import get_accessible_conversation
from app.database import get_db
from app.realtime.manager import realtime_manager

router = APIRouter(tags=["ai"])
logger = logging.getLogger(__name__)


def _as_ai_config_read(config: ChannelAiConfig) -> AiConfigRead:
    return AiConfigRead(
        id=config.id,
        channel_id=config.channel_id,
        is_enabled=bool(config.is_enabled),
        provider=config.provider or "openai",
        model_name=config.model_name or "gpt-4o-mini",
        has_api_key=bool(config.api_key_encrypted),
        system_prompt=config.system_prompt
        or "Você é o assistente virtual de atendimento da empresa. Responda com cordialidade, clareza e precisão.",
        bot_name=config.bot_name or "IA Assistente",
        handoff_prompt=config.handoff_prompt
        or "Transfira para um atendente humano se o cliente solicitar ou se a dúvida estiver fora do escopo.",
        temperature=float(config.temperature) if config.temperature is not None else 0.3,
        max_tokens=int(config.max_tokens) if config.max_tokens is not None else 500,
    )


@router.get(
    "/channels/{channel_id}/ai-config",
    response_model=AiConfigRead,
)
def get_channel_ai_config(
    channel_id: UUID,
    db: Session = Depends(get_db),
    context: AuthContext = Depends(get_auth_context),
) -> AiConfigRead:
    if context.membership.role != "admin":
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

    try:
        config = get_or_create_ai_config(db, context.tenant_id, channel.id)
        return _as_ai_config_read(config)
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception(
            "Failed to get/create AI config for channel %s (tenant %s): %s",
            channel_id,
            context.tenant_id,
            exc,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erro interno ao carregar configuração de IA: {type(exc).__name__}: {exc}",
        )


@router.put(
    "/channels/{channel_id}/ai-config",
    response_model=AiConfigRead,
)
def update_channel_ai_config(
    channel_id: UUID,
    payload: AiConfigUpdate,
    db: Session = Depends(get_db),
    context: AuthContext = Depends(get_auth_context),
) -> AiConfigRead:
    if context.membership.role != "admin":
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
    "/channels/{channel_id}/ai-simulator",
    response_model=AiSimulateResponse,
)
async def simulate_channel_ai(
    channel_id: UUID,
    payload: AiSimulateRequest,
    db: Session = Depends(get_db),
    context: AuthContext = Depends(get_auth_context),
) -> AiSimulateResponse:
    if context.membership.role != "admin":
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
    "/conversations/{conversation_id}/toggle-bot",
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

    await realtime_manager.broadcast(
        tenant_id=context.tenant_id,
        event="conversation.updated",
        data={
            "id": str(conversation.id),
            "channel_id": str(conversation.channel_id),
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


@router.post(
    "/conversations/{conversation_id}/summarize",
    response_model=AiSummaryResponse,
)
async def summarize_conversation(
    conversation_id: UUID,
    db: Session = Depends(get_db),
    context: AuthContext = Depends(get_auth_context),
) -> AiSummaryResponse:
    get_accessible_conversation(
        db,
        context,
        conversation_id,
    )

    try:
        summary = await summarize_conversation_history(
            db,
            context.tenant_id,
            conversation_id,
        )
        return AiSummaryResponse(
            summary=summary,
            generated_at=datetime.now(UTC).isoformat(),
        )
    except ValueError as err:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(err),
        )
    except Exception as err:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Falha ao gerar resumo com IA: {err}",
        )


@router.post(
    "/conversations/{conversation_id}/analyze",
    response_model=AiConversationAnalysisResponse,
)
async def analyze_conversation(
    conversation_id: UUID,
    db: Session = Depends(get_db),
    context: AuthContext = Depends(get_auth_context),
) -> AiConversationAnalysisResponse:
    get_accessible_conversation(db, context, conversation_id)

    try:
        analysis = await analyze_conversation_history(
            db,
            context.tenant_id,
            conversation_id,
        )
        return AiConversationAnalysisResponse(
            **analysis.model_dump(exclude={"generated_at"}),
            generated_at=datetime.now(UTC).isoformat(),
        )
    except ValueError as err:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(err))
    except Exception:
        logger.exception(
            "Failed to analyze conversation %s for tenant %s",
            conversation_id,
            context.tenant_id,
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Falha ao analisar a conversa com IA.",
        )
