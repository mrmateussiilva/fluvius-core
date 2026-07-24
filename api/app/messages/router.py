from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.attachments.models import MessageAttachment
from app.attachments.service import MAX_MEDIA_BYTES, message_type_for_upload
from app.auth.dependencies import AuthContext, get_auth_context
from app.channels.models import WhatsAppChannel
from app.common.enums import (
    ChannelStatus,
    MessageDirection,
    MessageStatus,
    MessageType,
)
from app.common.schemas import (
    MessageAttachmentResponse,
    MessageResponse,
    QuotedMessageResponse,
)
from app.contacts.models import Contact
from app.conversations.models import Conversation
from app.conversations.router import (
    ensure_conversation_assignee,
    get_tenant_conversation,
    get_tenant_conversation_for_update,
)
from app.database import get_db
from app.messages.models import Message
from app.messages.schemas import MessageCreate
from app.providers.base import SendResult
from app.providers.factory import get_provider
from app.providers.status_updates import reconcile_pending_status_events
from app.realtime.manager import realtime_manager
from app.storage.local import LocalStorageProvider


router = APIRouter(tags=["messages"])
OFFLINE_MESSAGE = "WhatsApp desconectado. Reconecte o canal antes de enviar mensagens."


def apply_send_result(
    message: Message,
    result: SendResult,
    *,
    confirmed_at: datetime | None = None,
) -> None:
    """Apply the delivery invariant independently of provider behavior."""
    if result.success and result.provider_message_id:
        message.status = MessageStatus.SENT
        message.provider_message_id = result.provider_message_id
        message.error = None
        message.sent_at = confirmed_at or datetime.now(UTC)
        return

    message.status = MessageStatus.FAILED
    message.provider_message_id = None
    message.error = result.error or "Provider não confirmou o envio com um identificador"
    message.sent_at = None


def conversation_delivery_context(
    db: Session, tenant_id: UUID, conversation_id: UUID, user_id: UUID
) -> tuple[Conversation, WhatsAppChannel, Contact]:
    conversation = get_tenant_conversation_for_update(
        db, tenant_id, conversation_id
    )
    ensure_conversation_assignee(conversation, user_id)
    channel = db.scalar(
        select(WhatsAppChannel).where(
            WhatsAppChannel.id == conversation.channel_id,
            WhatsAppChannel.tenant_id == tenant_id,
        )
    )
    contact = db.scalar(
        select(Contact).where(Contact.id == conversation.contact_id, Contact.tenant_id == tenant_id)
    )
    if channel is None or contact is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Conversa inconsistente")
    if channel.status != ChannelStatus.CONNECTED:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=OFFLINE_MESSAGE)
    return conversation, channel, contact


def get_tenant_message(
    db: Session,
    tenant_id: UUID,
    conversation_id: UUID,
    message_id: UUID,
) -> Message:
    message = db.scalar(
        select(Message).where(
            Message.id == message_id,
            Message.tenant_id == tenant_id,
            Message.conversation_id == conversation_id,
        )
    )
    if message is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Mensagem não encontrada",
        )
    return message


def message_response(
    db: Session,
    tenant_id: UUID,
    message: Message,
    reply_to: Message | None = None,
    attachments: list[MessageAttachment] | None = None,
) -> MessageResponse:
    if reply_to is None and message.reply_to_message_id:
        reply_to = db.scalar(
            select(Message).where(
                Message.id == message.reply_to_message_id,
                Message.tenant_id == tenant_id,
                Message.conversation_id == message.conversation_id,
            )
        )
    quoted = (
        QuotedMessageResponse(
            id=reply_to.id,
            direction=reply_to.direction,
            message_type=reply_to.message_type,
            body=reply_to.body,
        )
        if reply_to
        else None
    )
    if attachments is None:
        attachments = list(
            db.scalars(
                select(MessageAttachment).where(
                    MessageAttachment.tenant_id == tenant_id,
                    MessageAttachment.message_id == message.id,
                )
            )
        )
    return MessageResponse.model_validate(message).model_copy(
        update={
            "reply_to": quoted,
            "attachments": [
                MessageAttachmentResponse.model_validate(attachment)
                for attachment in attachments
            ],
        }
    )


def message_list_response(
    db: Session, tenant_id: UUID, messages: list[Message]
) -> list[MessageResponse]:
    reply_ids = {message.reply_to_message_id for message in messages if message.reply_to_message_id}
    replies = (
        {
            reply.id: reply
            for reply in db.scalars(
                select(Message).where(
                    Message.id.in_(reply_ids),
                    Message.tenant_id == tenant_id,
                    Message.conversation_id == messages[0].conversation_id,
                )
            )
        }
        if reply_ids
        else {}
    )
    attachments_by_message: dict[UUID, list[MessageAttachment]] = {}
    if messages:
        for attachment in db.scalars(
            select(MessageAttachment).where(
                MessageAttachment.tenant_id == tenant_id,
                MessageAttachment.message_id.in_([message.id for message in messages]),
            )
        ):
            attachments_by_message.setdefault(attachment.message_id, []).append(attachment)
    return [
        message_response(
            db,
            tenant_id,
            message,
            replies.get(message.reply_to_message_id),
            attachments_by_message.get(message.id, []),
        )
        for message in messages
    ]


async def deliver_message(
    db: Session,
    *,
    message: Message,
    channel: WhatsAppChannel,
    contact: Contact,
) -> list[Message]:
    provider = get_provider(channel.provider)
    reply_to = (
        get_tenant_message(
            db,
            message.tenant_id,
            message.conversation_id,
            message.reply_to_message_id,
        )
        if message.reply_to_message_id
        else None
    )
    try:
        participant = None
        if reply_to:
            participant = (
                contact.phone_number
                if reply_to.direction == MessageDirection.INCOMING
                else channel.phone_number or contact.phone_number
            )
        if message.message_type == MessageType.TEXT:
            result = await provider.send_text(
                channel,
                contact.phone_number,
                message.body or "",
                reply_to_provider_message_id=(
                    reply_to.provider_message_id if reply_to else None
                ),
                reply_to_participant=participant,
                idempotency_key=str(message.id),
            )
        else:
            attachment = db.scalar(
                select(MessageAttachment).where(
                    MessageAttachment.tenant_id == message.tenant_id,
                    MessageAttachment.message_id == message.id,
                )
            )
            if attachment is None:
                message.status = MessageStatus.FAILED
                message.error = "Anexo da mensagem não foi encontrado"
                return []
            result = await provider.send_media(
                channel,
                contact.phone_number,
                attachment.public_url,
                message.body,
                reply_to_provider_message_id=(
                    reply_to.provider_message_id if reply_to else None
                ),
                reply_to_participant=participant,
                idempotency_key=str(message.id),
            )
        apply_send_result(message, result)
    except NotImplementedError as exc:
        message.status = MessageStatus.FAILED
        message.error = str(exc)
        message.sent_at = None
    db.flush()
    return reconcile_pending_status_events(
        db,
        channel=channel,
        provider_message_id=message.provider_message_id,
    )


@router.get("/conversations/{conversation_id}/messages", response_model=list[MessageResponse])
def list_messages(
    conversation_id: UUID,
    context: AuthContext = Depends(get_auth_context),
    db: Session = Depends(get_db),
) -> list[MessageResponse]:
    get_tenant_conversation(db, context.tenant_id, conversation_id)
    messages = list(
        db.scalars(
            select(Message)
            .where(
                Message.tenant_id == context.tenant_id,
                Message.conversation_id == conversation_id,
            )
            .order_by(Message.created_at)
        )
    )
    return message_list_response(db, context.tenant_id, messages)


@router.post(
    "/conversations/{conversation_id}/messages",
    response_model=MessageResponse,
    status_code=status.HTTP_201_CREATED,
)
async def send_message(
    conversation_id: UUID,
    payload: MessageCreate,
    context: AuthContext = Depends(get_auth_context),
    db: Session = Depends(get_db),
) -> MessageResponse:
    conversation, channel, contact = conversation_delivery_context(
        db, context.tenant_id, conversation_id, context.user.id
    )
    existing = db.scalar(
        select(Message).where(
            Message.id == payload.client_message_id,
            Message.tenant_id == context.tenant_id,
            Message.conversation_id == conversation_id,
        )
    )
    if existing is not None:
        if (
            existing.direction == MessageDirection.OUTGOING
            and existing.message_type == MessageType.TEXT
            and existing.body == payload.text
            and existing.reply_to_message_id == payload.reply_to_message_id
        ):
            return message_response(db, context.tenant_id, existing)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Identificador de mensagem já utilizado",
        )
    reply_to = None
    if payload.reply_to_message_id:
        reply_to = get_tenant_message(
            db,
            context.tenant_id,
            conversation_id,
            payload.reply_to_message_id,
        )
        if not reply_to.provider_message_id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="A mensagem citada ainda não foi confirmada pelo WhatsApp",
            )
    attempted_at = datetime.now(UTC)
    message = Message(
        id=payload.client_message_id,
        tenant_id=context.tenant_id,
        conversation_id=conversation_id,
        sender_user_id=context.user.id,
        reply_to_message_id=reply_to.id if reply_to else None,
        reply_to_provider_message_id=reply_to.provider_message_id if reply_to else None,
        direction=MessageDirection.OUTGOING,
        message_type=MessageType.TEXT,
        status=MessageStatus.PENDING,
        body=payload.text,
        attempt_count=1,
        last_attempt_at=attempted_at,
    )
    db.add(message)
    conversation.last_message_at = attempted_at
    db.commit()  # Persist pending before performing an external side effect.
    reconciled = await deliver_message(
        db, message=message, channel=channel, contact=contact
    )
    db.commit()
    db.refresh(message)
    await realtime_manager.broadcast(
        context.tenant_id,
        "message.created",
        message_response(db, context.tenant_id, message).model_dump(mode="json"),
    )
    for updated in reconciled:
        if updated.id != message.id:
            await realtime_manager.broadcast(
                context.tenant_id,
                "message.updated",
                message_response(db, context.tenant_id, updated).model_dump(mode="json"),
            )
    return message_response(db, context.tenant_id, message, reply_to)


@router.post(
    "/conversations/{conversation_id}/attachments",
    response_model=MessageResponse,
    status_code=status.HTTP_201_CREATED,
)
async def send_attachment(
    conversation_id: UUID,
    file: UploadFile = File(...),
    caption: str | None = Form(default=None),
    reply_to_message_id: UUID | None = Form(default=None),
    context: AuthContext = Depends(get_auth_context),
    db: Session = Depends(get_db),
) -> MessageResponse:
    conversation, channel, contact = conversation_delivery_context(
        db, context.tenant_id, conversation_id, context.user.id
    )
    reply_to = None
    if reply_to_message_id:
        reply_to = get_tenant_message(
            db,
            context.tenant_id,
            conversation_id,
            reply_to_message_id,
        )
        if not reply_to.provider_message_id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="A mensagem citada ainda não foi confirmada pelo WhatsApp",
            )
    content = await file.read()
    if not content or len(content) > MAX_MEDIA_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="Anexo deve ter até 25 MB",
        )
    content_type = file.content_type or "application/octet-stream"
    message_type = message_type_for_upload(
        content_type,
        file.filename or "anexo",
    )
    stored = await LocalStorageProvider().save(
        str(context.tenant_id), file.filename or "anexo", content
    )
    attempted_at = datetime.now(UTC)
    message = Message(
        tenant_id=context.tenant_id,
        conversation_id=conversation_id,
        sender_user_id=context.user.id,
        reply_to_message_id=reply_to.id if reply_to else None,
        reply_to_provider_message_id=reply_to.provider_message_id if reply_to else None,
        direction=MessageDirection.OUTGOING,
        message_type=message_type,
        status=MessageStatus.PENDING,
        body=caption,
        attempt_count=1,
        last_attempt_at=attempted_at,
    )
    db.add(message)
    conversation.last_message_at = attempted_at
    db.flush()
    db.add(
        MessageAttachment(
            tenant_id=context.tenant_id,
            message_id=message.id,
            file_name=file.filename or "anexo",
            content_type=content_type,
            size_bytes=stored.size_bytes,
            storage_key=stored.key,
            public_url=stored.public_url,
        )
    )
    db.commit()
    reconciled = await deliver_message(
        db, message=message, channel=channel, contact=contact
    )
    db.commit()
    db.refresh(message)
    await realtime_manager.broadcast(
        context.tenant_id,
        "message.created",
        message_response(db, context.tenant_id, message).model_dump(mode="json"),
    )
    for updated in reconciled:
        if updated.id != message.id:
            await realtime_manager.broadcast(
                context.tenant_id,
                "message.updated",
                message_response(db, context.tenant_id, updated).model_dump(mode="json"),
            )
    return message_response(db, context.tenant_id, message, reply_to)


@router.post(
    "/conversations/{conversation_id}/messages/{message_id}/retry",
    response_model=MessageResponse,
)
async def retry_message(
    conversation_id: UUID,
    message_id: UUID,
    context: AuthContext = Depends(get_auth_context),
    db: Session = Depends(get_db),
) -> MessageResponse:
    conversation, channel, contact = conversation_delivery_context(
        db, context.tenant_id, conversation_id, context.user.id
    )
    message = get_tenant_message(db, context.tenant_id, conversation_id, message_id)
    if message.direction != MessageDirection.OUTGOING or message.status != MessageStatus.FAILED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Somente mensagens de saída com falha podem ser reenviadas",
        )

    attempted_at = datetime.now(UTC)
    message.status = MessageStatus.PENDING
    message.error = None
    message.provider_message_id = None
    message.sent_at = None
    message.delivered_at = None
    message.read_at = None
    message.attempt_count += 1
    message.last_attempt_at = attempted_at
    conversation.last_message_at = attempted_at
    db.commit()  # Persist the retry intent before calling the provider.

    reconciled = await deliver_message(
        db, message=message, channel=channel, contact=contact
    )
    db.commit()
    db.refresh(message)
    await realtime_manager.broadcast(
        context.tenant_id,
        "message.updated",
        message_response(db, context.tenant_id, message).model_dump(mode="json"),
    )
    for updated in reconciled:
        if updated.id != message.id:
            await realtime_manager.broadcast(
                context.tenant_id,
                "message.updated",
                message_response(db, context.tenant_id, updated).model_dump(mode="json"),
            )
    return message_response(db, context.tenant_id, message)
