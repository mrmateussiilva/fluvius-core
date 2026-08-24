import json
import logging
from datetime import UTC, datetime
from uuid import UUID

import httpx
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.ai.models import ChannelAiConfig
from app.ai.schemas import AiConfigUpdate, AiSimulateRequest, AiSimulateResponse
from app.channels.models import WhatsAppChannel
from app.common.enums import (
    ChannelStatus,
    ContactKind,
    MessageDirection,
    MessageStatus,
    MessageType,
)
from app.contacts.models import Contact
from app.conversations.models import Conversation
from app.delivery.dispatcher import create_delivery, dispatch_delivery
from app.delivery.models import MessageDelivery
from app.messages.models import Message
from app.realtime.manager import realtime_manager
from app.security import decrypt_secret, encrypt_secret

logger = logging.getLogger(__name__)

HANDOFF_TOOL = {
    "type": "function",
    "function": {
        "name": "solicitar_atendente_humano",
        "description": "Transfere o atendimento para um atendente humano da equipe quando o cliente solicitar falar com uma pessoa, quando houver reclamação, ou quando a dúvida estiver fora da sua base de conhecimento.",
        "parameters": {
            "type": "object",
            "properties": {
                "motivo": {
                    "type": "string",
                    "description": "Motivo claro e resumido da transferência para a equipe humana (ex: 'Cliente solicitou atendente', 'Dúvida financeira complexa', 'Reclamação de entrega').",
                },
                "mensagem_ao_cliente": {
                    "type": "string",
                    "description": "Mensagem cordial e empática informando ao cliente que você está transferindo a conversa para a equipe humana.",
                },
            },
            "required": ["motivo"],
        },
    },
}

DEFAULT_HANDOFF_MESSAGE = (
    "Entendido! Estou transferindo seu atendimento para a nossa equipe humana. "
    "Um de nossos atendentes irá te responder em instantes."
)


def get_or_create_ai_config(
    db: Session, tenant_id: UUID, channel_id: UUID
) -> ChannelAiConfig:
    config = db.scalar(
        select(ChannelAiConfig).where(
            ChannelAiConfig.tenant_id == tenant_id,
            ChannelAiConfig.channel_id == channel_id,
        )
    )
    if config is None:
        config = ChannelAiConfig(
            tenant_id=tenant_id,
            channel_id=channel_id,
            is_enabled=False,
            provider="openai",
            model_name="gpt-4o-mini",
            bot_name="IA Assistente",
            system_prompt=(
                "Você é o assistente virtual de atendimento da empresa. "
                "Responda às dúvidas dos clientes de forma educada, precisa e profissional."
            ),
            handoff_prompt=(
                "Se o cliente solicitar falar com um atendente humano ou se você não tiver certeza "
                "da resposta, use a ferramenta 'solicitar_atendente_humano' para transferi-lo."
            ),
            temperature=0.3,
            max_tokens=500,
        )
        db.add(config)
        db.commit()
        db.refresh(config)
    return config


def update_ai_config(
    db: Session, tenant_id: UUID, channel_id: UUID, payload: AiConfigUpdate
) -> ChannelAiConfig:
    config = get_or_create_ai_config(db, tenant_id, channel_id)

    if payload.is_enabled is not None:
        config.is_enabled = payload.is_enabled
    if payload.provider is not None:
        config.provider = payload.provider.strip().lower()
    if payload.model_name is not None:
        config.model_name = payload.model_name.strip()
    if payload.system_prompt is not None:
        config.system_prompt = payload.system_prompt.strip()
    if payload.bot_name is not None:
        config.bot_name = payload.bot_name.strip()
    if payload.handoff_prompt is not None:
        config.handoff_prompt = payload.handoff_prompt.strip()
    if payload.temperature is not None:
        config.temperature = payload.temperature
    if payload.max_tokens is not None:
        config.max_tokens = payload.max_tokens

    if payload.api_key is not None:
        stripped = payload.api_key.strip()
        if stripped:
            config.api_key_encrypted = encrypt_secret(stripped)
        else:
            config.api_key_encrypted = None

    db.commit()
    db.refresh(config)
    return config


def _resolve_provider_endpoint(provider: str) -> str:
    prov = provider.strip().lower()
    if prov == "groq":
        return "https://api.groq.com/openai/v1/chat/completions"
    if prov == "gemini":
        return "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
    if prov == "deepseek":
        return "https://api.deepseek.com/chat/completions"
    # Default is standard OpenAI endpoint
    return "https://api.openai.com/v1/chat/completions"


async def call_llm(
    provider: str,
    model_name: str,
    api_key: str,
    system_prompt: str,
    conversation_messages: list[dict[str, str]],
    handoff_prompt: str | None = None,
    temperature: float = 0.3,
    max_tokens: int = 500,
) -> tuple[str, bool, str | None]:
    """Calls the LLM provider using OpenAI-compatible Chat Completions API with Tool Calling.

    Returns:
        (reply_text, handoff_triggered, handoff_reason)
    """
    endpoint = _resolve_provider_endpoint(provider)
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    full_system = system_prompt
    if handoff_prompt:
        full_system += f"\n\nInstruções de Transbordo (Handoff):\n{handoff_prompt}"

    messages_payload: list[dict] = [{"role": "system", "content": full_system}]
    for msg in conversation_messages:
        messages_payload.append({"role": msg["role"], "content": msg["content"]})

    body: dict = {
        "model": model_name,
        "messages": messages_payload,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "tools": [HANDOFF_TOOL],
        "tool_choice": "auto",
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(endpoint, headers=headers, json=body)
        if response.status_code != 200:
            logger.error("LLM API Error %s: %s", response.status_code, response.text)
            raise RuntimeError(f"Erro no provedor de IA ({response.status_code}): {response.text}")

        data = response.json()
        choice = data.get("choices", [{}])[0]
        message = choice.get("message", {})

        # Check for Tool Call
        tool_calls = message.get("tool_calls") or []
        for tool_call in tool_calls:
            func = tool_call.get("function", {})
            if func.get("name") == "solicitar_atendente_humano":
                try:
                    args = json.loads(func.get("arguments", "{}"))
                except Exception:
                    args = {}
                reason = args.get("motivo") or "Cliente solicitou atendimento humano"
                reply = args.get("mensagem_ao_cliente") or DEFAULT_HANDOFF_MESSAGE
                return reply, True, reason

        content = (message.get("content") or "").strip()
        if not content:
            content = "Desculpe, não consegui processar a resposta no momento."
        return content, False, None


async def simulate_ai(
    db: Session, tenant_id: UUID, channel_id: UUID, req: AiSimulateRequest
) -> AiSimulateResponse:
    config = get_or_create_ai_config(db, tenant_id, channel_id)
    if not config.api_key_encrypted:
        raise ValueError("Chave de API não configurada para este canal.")

    api_key = decrypt_secret(config.api_key_encrypted)
    system_prompt = req.system_prompt or config.system_prompt
    handoff_prompt = req.handoff_prompt or config.handoff_prompt

    messages = [{"role": m.role, "content": m.content} for m in req.messages]

    reply, handoff_triggered, handoff_reason = await call_llm(
        provider=config.provider,
        model_name=config.model_name,
        api_key=api_key,
        system_prompt=system_prompt,
        conversation_messages=messages,
        handoff_prompt=handoff_prompt,
        temperature=config.temperature,
        max_tokens=config.max_tokens,
    )

    return AiSimulateResponse(
        reply=reply,
        handoff_triggered=handoff_triggered,
        handoff_reason=handoff_reason,
    )


async def execute_ai_turn(
    db: Session,
    tenant_id: UUID,
    conversation_id: UUID,
) -> None:
    """Executes an AI turn for a conversation that has an active bot."""
    conversation = db.scalar(
        select(Conversation).where(
            Conversation.id == conversation_id,
            Conversation.tenant_id == tenant_id,
        )
    )
    if conversation is None:
        return

    # Invariants:
    # 1. Bot only operates if is_bot_active is True
    # 2. Bot never runs if an assigned user is present (human operator sovereignty)
    # 3. Bot only runs if conversation status is 'new'
    if (
        not conversation.is_bot_active
        or conversation.assigned_user_id is not None
        or conversation.status != "new"
    ):
        return

    channel = db.scalar(
        select(WhatsAppChannel).where(
            WhatsAppChannel.id == conversation.channel_id,
            WhatsAppChannel.tenant_id == tenant_id,
        )
    )
    if channel is None or channel.status != ChannelStatus.CONNECTED:
        return

    config = db.scalar(
        select(ChannelAiConfig).where(
            ChannelAiConfig.tenant_id == tenant_id,
            ChannelAiConfig.channel_id == channel.id,
        )
    )
    if config is None or not config.is_enabled or not config.api_key_encrypted:
        return

    contact = db.scalar(
        select(Contact).where(
            Contact.id == conversation.contact_id,
            Contact.tenant_id == tenant_id,
        )
    )
    if contact is None or contact.kind == ContactKind.GROUP:
        # Do not run auto-bot inside WhatsApp groups
        return

    # Fetch last 10 messages for context
    recent_msgs = list(
        db.scalars(
            select(Message)
            .where(
                Message.tenant_id == tenant_id,
                Message.conversation_id == conversation.id,
            )
            .order_by(desc(Message.created_at))
            .limit(10)
        )
    )
    recent_msgs.reverse()

    if not recent_msgs:
        return

    # Don't respond if last message was already outgoing
    if recent_msgs[-1].direction == MessageDirection.OUTGOING:
        return

    history_payload = []
    for msg in recent_msgs:
        role = "assistant" if msg.direction == MessageDirection.OUTGOING else "user"
        body = msg.body or f"[{msg.message_type.value}]"
        history_payload.append({"role": role, "content": body})

    api_key = decrypt_secret(config.api_key_encrypted)

    try:
        reply_text, handoff_triggered, handoff_reason = await call_llm(
            provider=config.provider,
            model_name=config.model_name,
            api_key=api_key,
            system_prompt=config.system_prompt,
            conversation_messages=history_payload,
            handoff_prompt=config.handoff_prompt,
            temperature=config.temperature,
            max_tokens=config.max_tokens,
        )
    except Exception as exc:
        logger.error("Failed to execute AI turn for conversation %s: %s", conversation_id, exc)
        return

    # Re-verify conversation state under lock before persisting response
    conv_check = db.scalar(
        select(Conversation)
        .where(
            Conversation.id == conversation_id,
            Conversation.tenant_id == tenant_id,
        )
        .with_for_update()
    )
    if (
        conv_check is None
        or not conv_check.is_bot_active
        or conv_check.assigned_user_id is not None
        or conv_check.status != "new"
    ):
        # Operator assumed the conversation during the LLM call! Abort AI response.
        logger.info("Human operator took over conversation %s during LLM call; aborting AI response", conversation_id)
        return

    now = datetime.now(UTC)

    if handoff_triggered:
        conv_check.is_bot_active = False
        conv_check.bot_handoff_at = now
        conv_check.bot_handoff_reason = handoff_reason or "Transbordo automático solicitado pela IA"

    # Create outgoing message
    ai_message = Message(
        tenant_id=tenant_id,
        conversation_id=conversation_id,
        direction=MessageDirection.OUTGOING,
        message_type=MessageType.TEXT,
        status=MessageStatus.PENDING,
        body=reply_text,
        sender_name=config.bot_name or "IA Assistente",
        is_bot=True,
    )
    db.add(ai_message)
    conv_check.last_message_at = now
    db.flush()

    delivery = create_delivery(db, ai_message, channel.provider)
    db.commit()
    db.refresh(ai_message)

    # Dispatch to gateway outbox
    dispatch_delivery(delivery.id)

    # Broadcast to realtime subscribers
    await realtime_manager.publish_tenant(
        tenant_id=tenant_id,
        event="message:created",
        data={
            "id": str(ai_message.id),
            "conversation_id": str(conversation_id),
            "direction": ai_message.direction.value,
            "message_type": ai_message.message_type.value,
            "status": ai_message.status.value,
            "body": ai_message.body,
            "sender_name": ai_message.sender_name,
            "is_bot": True,
            "created_at": ai_message.created_at.isoformat(),
        },
    )
    await realtime_manager.publish_tenant(
        tenant_id=tenant_id,
        event="conversation:updated",
        data={
            "id": str(conv_check.id),
            "status": conv_check.status.value,
            "is_bot_active": conv_check.is_bot_active,
            "bot_handoff_at": conv_check.bot_handoff_at.isoformat() if conv_check.bot_handoff_at else None,
            "bot_handoff_reason": conv_check.bot_handoff_reason,
            "last_message_at": conv_check.last_message_at.isoformat() if conv_check.last_message_at else None,
            "last_message_body": ai_message.body,
            "last_message_type": ai_message.message_type.value,
            "last_message_direction": ai_message.direction.value,
        },
    )
