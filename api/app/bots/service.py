"""Small engine switch, with the native AI implementation left in app.ai."""

import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.ai.service import DEFAULT_HANDOFF_MESSAGE, detect_forced_handoff, execute_ai_turn
from app.bots.configuration import configured_engine, end_bot_sessions, get_typebot_config
from app.bots.models import BotSession, BotTurn
from app.bots.typebot.client import TypebotClient, TypebotError
from app.channels.models import WhatsAppChannel
from app.common.enums import (
    ChannelStatus,
    ContactKind,
    MessageDirection,
    MessageStatus,
    MessageType,
)
from app.config import settings
from app.contacts.models import Contact
from app.conversations.models import Conversation
from app.database import SessionLocal
from app.delivery.dispatcher import create_delivery, dispatch_delivery
from app.messages.models import Message
from app.realtime.manager import realtime_manager

logger = logging.getLogger(__name__)


def eligible(conversation: Conversation) -> bool:
    return bool(
        conversation.is_bot_active
        and conversation.assigned_user_id is None
        and conversation.status == "new"
    )


def prepare_typebot_turn(db: Session, conversation: Conversation, message: Message) -> None:
    """Called under the inbound conversation lock, before its commit."""
    tenant_id = conversation.tenant_id
    config = get_typebot_config(db, tenant_id, conversation.channel_id)
    if not config or not config.is_enabled or not eligible(conversation):
        return
    if message.direction != MessageDirection.INCOMING:
        return
    existing = db.scalar(
        select(BotTurn.id).where(BotTurn.tenant_id == tenant_id, BotTurn.message_id == message.id)
    )
    if existing:
        return
    session = db.scalar(
        select(BotSession).where(
            BotSession.tenant_id == tenant_id,
            BotSession.conversation_id == conversation.id,
            BotSession.status == "active",
        )
    )
    if session and session.public_id != config.public_id:
        end_bot_sessions(db, tenant_id, conversation.id)
        session = None
    if session is None:
        session = BotSession(
            tenant_id=tenant_id, conversation_id=conversation.id, public_id=config.public_id
        )
        db.add(session)
        db.flush()
    db.add(
        BotTurn(
            tenant_id=tenant_id,
            session_id=session.id,
            message_id=message.id,
            created_at=datetime.now(UTC),
        )
    )


@asynccontextmanager
async def _conversation_turn_lock(tenant_id: UUID, conversation_id: UUID):
    # A separate transaction keeps this lock across the durable POST claim commit.
    # No conversation/session row is locked during HTTP: a human can take over.
    with SessionLocal() as lock_db:
        params = {"key": f"bot:{tenant_id}:{conversation_id}"}
        while not lock_db.scalar(
            text("SELECT pg_try_advisory_xact_lock(hashtextextended(:key, 0))"), params
        ):
            await asyncio.sleep(0.05)
        yield


async def execute_bot_turn(*, tenant_id: UUID, conversation_id: UUID) -> None:
    with SessionLocal() as db:
        conversation = db.scalar(
            select(Conversation).where(
                Conversation.tenant_id == tenant_id,
                Conversation.id == conversation_id,
            )
        )
        if conversation is None:
            return
        engine = configured_engine(db, tenant_id, conversation.channel_id)
        if engine == "native_ai":
            await execute_ai_turn(db, tenant_id, conversation_id)
        elif engine == "typebot":
            # Commit the routing read before taking the bot lock and reloading state.
            db.rollback()
            async with _conversation_turn_lock(tenant_id, conversation_id):
                while await _execute_typebot_turn(db, tenant_id, conversation_id):
                    pass


def _context(db: Session, tenant_id: UUID, conversation_id: UUID, *, lock=False):
    conversation = db.scalar(
        select(Conversation)
        .where(
            Conversation.tenant_id == tenant_id,
            Conversation.id == conversation_id,
        )
        .execution_options(populate_existing=True)
    )
    if conversation is None:
        return None
    channel_query = (
        select(WhatsAppChannel)
        .where(
            WhatsAppChannel.tenant_id == tenant_id,
            WhatsAppChannel.id == conversation.channel_id,
        )
        .execution_options(populate_existing=True)
    )
    channel = db.scalar(channel_query.with_for_update() if lock else channel_query)
    if lock:
        conversation = db.scalar(
            select(Conversation)
            .where(
                Conversation.tenant_id == tenant_id,
                Conversation.id == conversation_id,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    if (
        conversation is None
        or not eligible(conversation)
        or channel is None
        or channel.status != ChannelStatus.CONNECTED
    ):
        return None
    config = get_typebot_config(db, tenant_id, channel.id)
    contact = db.scalar(
        select(Contact)
        .where(
            Contact.tenant_id == tenant_id,
            Contact.id == conversation.contact_id,
        )
        .execution_options(populate_existing=True)
    )
    if not config or not config.is_enabled or not contact or contact.kind == ContactKind.GROUP:
        return None
    return conversation, channel, config, contact


async def _execute_typebot_turn(db: Session, tenant_id: UUID, conversation_id: UUID) -> bool:
    row = db.execute(
        select(BotTurn, BotSession)
        .join(BotSession, BotSession.id == BotTurn.session_id)
        .where(
            BotTurn.tenant_id == tenant_id,
            BotSession.tenant_id == tenant_id,
            BotSession.conversation_id == conversation_id,
            BotTurn.status.in_(("queued", "processing")),
        )
        .order_by(BotTurn.created_at, BotTurn.id)
        .limit(1)
        .execution_options(populate_existing=True)
    ).first()
    if row is None:
        return False
    turn, session = row
    context = _context(db, tenant_id, conversation_id)
    if context is None or session.status != "active" or session.public_id != context[2].public_id:
        turn.status = "discarded"
        if context is None:
            end_bot_sessions(db, tenant_id, conversation_id)
        db.commit()
        return True
    conversation, channel, config, contact = context
    original_channel_id, original_contact_id = channel.id, contact.id
    message = db.scalar(
        select(Message).where(
            Message.tenant_id == tenant_id,
            Message.id == turn.message_id,
            Message.conversation_id == conversation_id,
            Message.direction == MessageDirection.INCOMING,
        )
    )
    if message is None:
        turn.status = "discarded"
        db.commit()
        return True
    # A previous worker died after claiming this POST. Its outcome is ambiguous.
    reason = (
        "typebot_unavailable"
        if turn.status == "processing"
        else detect_forced_handoff(message.body)
    )
    texts = [DEFAULT_HANDOFF_MESSAGE] if reason and reason != "typebot_unavailable" else []
    if message.message_type != MessageType.TEXT or not message.body:
        reason = "typebot_unsupported_input"
    session_id, public_id = session.external_session_id, session.public_id
    body = message.body or ""
    variables = {
        "fluvius_conversation_id": str(conversation_id),
        "fluvius_contact_id": str(contact.id),
        "fluvius_channel_id": str(channel.id),
        "fluvius_initial_message": body,
    }
    if contact.name or contact.push_name:
        variables["contact_name"] = contact.name or contact.push_name
    turn.status = "processing"
    db.commit()  # Persist before any non-idempotent HTTP effect; never retry it blindly.
    reply = None
    if reason is None:
        try:
            client = TypebotClient(settings.typebot_base_url)
            reply = (
                await client.continue_chat(session_id, body)
                if session_id
                else await client.start(public_id, body, variables)
            )
            texts = reply.texts
        except TypebotError as exc:
            logger.warning(
                "Typebot unavailable; tenant=%s conversation=%s code=%s",
                tenant_id,
                conversation_id,
                str(exc),
            )
            reason = "typebot_unavailable"

    context = _context(db, tenant_id, conversation_id, lock=True)
    session = db.scalar(
        select(BotSession)
        .where(
            BotSession.tenant_id == tenant_id,
            BotSession.id == turn.session_id,
            BotSession.conversation_id == conversation_id,
        )
        .execution_options(populate_existing=True)
    )
    if (
        context is None
        or context[1].id != original_channel_id
        or context[3].id != original_contact_id
        or session is None
        or session.status != "active"
        or session.public_id != context[2].public_id
    ):
        turn.status = "discarded"
        if context is None:
            end_bot_sessions(db, tenant_id, conversation_id)
        db.commit()
        return True
    conversation, channel, _, _ = context
    now = datetime.now(UTC)
    if reply:
        if reply.session_id:
            session.external_session_id = reply.session_id
        if reply.result_id:
            session.result_id = reply.result_id
    if reason:
        conversation.is_bot_active = False
        conversation.bot_handoff_at = now
        conversation.bot_handoff_reason = reason
    if reason or (reply and reply.finished):
        # Natural completion ends this execution, not the conversation's automation.
        session.status = "failed" if reason == "typebot_unavailable" else "ended"
        session.ended_at = now
    turn.status = "failed" if reason == "typebot_unavailable" else "completed"
    outgoing = []
    for position, body in enumerate(texts):
        # Delivery orders by (created_at, id); transaction-default timestamps tie.
        created_at = now + timedelta(microseconds=position)
        message = Message(
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            direction=MessageDirection.OUTGOING,
            message_type=MessageType.TEXT,
            status=MessageStatus.PENDING,
            body=body,
            sender_name="Typebot",
            is_bot=True,
            created_at=created_at,
        )
        db.add(message)
        db.flush()
        delivery = create_delivery(tenant_id=tenant_id, message_id=message.id, now=created_at)
        db.add(delivery)
        outgoing.append((message, delivery))
        conversation.last_message_at = created_at
    db.commit()
    for message, delivery in outgoing:
        dispatch_delivery(delivery.id, tenant_id)
        await realtime_manager.broadcast(
            tenant_id,
            "message.created",
            {
                "id": str(message.id),
                "conversation_id": str(conversation_id),
                "channel_id": str(channel.id),
                "direction": message.direction.value,
                "message_type": message.message_type.value,
                "status": message.status.value,
                "body": message.body,
                "is_bot": True,
                "sender_name": message.sender_name,
                "created_at": message.created_at.isoformat(),
            },
        )
    await realtime_manager.broadcast(
        tenant_id,
        "conversation.updated",
        {
            "id": str(conversation_id),
            "channel_id": str(channel.id),
            "status": conversation.status.value,
            "is_bot_active": conversation.is_bot_active,
            "bot_handoff_reason": conversation.bot_handoff_reason,
            "bot_handoff_at": conversation.bot_handoff_at.isoformat()
            if conversation.bot_handoff_at
            else None,
            "last_message_at": conversation.last_message_at.isoformat()
            if conversation.last_message_at
            else None,
        },
    )
    return True
