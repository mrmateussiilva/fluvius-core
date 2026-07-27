import asyncio
from datetime import UTC, datetime
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.attachments.models import MessageAttachment
from app.attachments.service import (
    MAX_MEDIA_BYTES,
    UnsupportedAttachmentError,
    validate_outgoing_attachment,
)
from app.auth.dependencies import AuthContext, get_auth_context
from app.channels.models import WhatsAppChannel
from app.common.enums import (
    ChannelProvider,
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
    get_accessible_conversation,
)
from app.database import get_db
from app.delivery.dispatcher import create_delivery, dispatch_delivery
from app.delivery.models import MessageDelivery
from app.delivery.service import (
    apply_send_result as apply_send_result,
    format_outgoing_content as format_outgoing_content,
    normalized_sender_name,
)
from app.messages.models import Message
from app.messages.schemas import MessageCreate
from app.providers.evolution_credentials import (
    ProviderConfigurationError,
    claim_evolution_credential,
)
from app.realtime.manager import realtime_manager
from app.storage.local import LocalStorageProvider

router = APIRouter(tags=["messages"])
OFFLINE_MESSAGE = "WhatsApp desconectado. Reconecte o canal antes de enviar mensagens."
def conversation_delivery_context(
    db: Session,
    context: AuthContext,
    conversation_id: UUID,
) -> tuple[Conversation, WhatsAppChannel, Contact]:
    conversation = get_accessible_conversation(
        db,
        context,
        conversation_id,
        for_update=True,
    )
    ensure_conversation_assignee(conversation, context.user.id)
    channel = db.scalar(
        select(WhatsAppChannel).where(
            WhatsAppChannel.id == conversation.channel_id,
            WhatsAppChannel.tenant_id == context.tenant_id,
        )
    )
    contact = db.scalar(
        select(Contact).where(
            Contact.id == conversation.contact_id,
            Contact.tenant_id == context.tenant_id,
        )
    )
    if channel is None or contact is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Conversa inconsistente")
    if channel.status != ChannelStatus.CONNECTED:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=OFFLINE_MESSAGE)
    if channel.provider == ChannelProvider.EVOLUTION_GO:
        try:
            claim_evolution_credential(db, channel)
        except ProviderConfigurationError as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=str(exc),
            ) from exc
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
            sender_name=reply_to.sender_name,
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


def ensure_delivery(
    db: Session,
    message: Message,
    *,
    reset: bool = False,
) -> MessageDelivery:
    delivery = db.scalar(
        select(MessageDelivery).where(
            MessageDelivery.message_id == message.id,
            MessageDelivery.tenant_id == message.tenant_id,
        )
    )
    if delivery is None:
        delivery = create_delivery(
            tenant_id=message.tenant_id,
            message_id=message.id,
        )
        db.add(delivery)
    elif reset:
        delivery.status = "queued"
        delivery.attempt_count = 0
        delivery.next_attempt_at = datetime.now(UTC)
        delivery.locked_at = None
        delivery.rq_job_id = None
        delivery.last_error = None
        delivery.completed_at = None
    return delivery


@router.get("/conversations/{conversation_id}/messages", response_model=list[MessageResponse])
def list_messages(
    conversation_id: UUID,
    context: AuthContext = Depends(get_auth_context),
    db: Session = Depends(get_db),
) -> list[MessageResponse]:
    get_accessible_conversation(db, context, conversation_id)
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
    status_code=status.HTTP_202_ACCEPTED,
)
async def send_message(
    conversation_id: UUID,
    payload: MessageCreate,
    context: AuthContext = Depends(get_auth_context),
    db: Session = Depends(get_db),
) -> MessageResponse:
    conversation, _, _ = conversation_delivery_context(
        db,
        context,
        conversation_id,
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
            and existing.sender_user_id == context.user.id
            and existing.body == payload.text
            and existing.reply_to_message_id == payload.reply_to_message_id
        ):
            if existing.status == MessageStatus.PENDING:
                delivery = ensure_delivery(db, existing)
                db.commit()
                await asyncio.to_thread(
                    dispatch_delivery,
                    delivery.id,
                    context.tenant_id,
                )
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
    created_at = datetime.now(UTC)
    message = Message(
        id=payload.client_message_id,
        tenant_id=context.tenant_id,
        conversation_id=conversation_id,
        sender_user_id=context.user.id,
        sender_name=normalized_sender_name(context.user.name),
        reply_to_message_id=reply_to.id if reply_to else None,
        reply_to_provider_message_id=reply_to.provider_message_id if reply_to else None,
        direction=MessageDirection.OUTGOING,
        message_type=MessageType.TEXT,
        status=MessageStatus.PENDING,
        body=payload.text,
        attempt_count=0,
    )
    db.add(message)
    conversation.last_message_at = created_at
    db.flush()
    delivery = create_delivery(
        tenant_id=context.tenant_id,
        message_id=message.id,
        now=created_at,
    )
    db.add(delivery)
    db.commit()
    db.refresh(message)
    await realtime_manager.broadcast(
        context.tenant_id,
        "message.created",
        {
            **message_response(
                db,
                context.tenant_id,
                message,
            ).model_dump(mode="json"),
            "channel_id": str(conversation.channel_id),
        },
    )
    await asyncio.to_thread(
        dispatch_delivery,
        delivery.id,
        context.tenant_id,
    )
    return message_response(db, context.tenant_id, message, reply_to)


@router.post(
    "/conversations/{conversation_id}/attachments",
    response_model=MessageResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def send_attachment(
    conversation_id: UUID,
    file: UploadFile = File(...),
    caption: str | None = Form(default=None),
    reply_to_message_id: UUID | None = Form(default=None),
    client_message_id: UUID | None = Form(default=None),
    context: AuthContext = Depends(get_auth_context),
    db: Session = Depends(get_db),
) -> MessageResponse:
    conversation, _, _ = conversation_delivery_context(
        db,
        context,
        conversation_id,
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
    content = await file.read(MAX_MEDIA_BYTES + 1)
    if not content or len(content) > MAX_MEDIA_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="Anexo deve ter até 25 MB",
        )
    file_name = file.filename or "anexo"
    try:
        validated = validate_outgoing_attachment(
            file.content_type or "application/octet-stream",
            file_name,
            content,
        )
    except UnsupportedAttachmentError as exc:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=str(exc),
        ) from exc

    normalized_caption = (
        None if validated.message_type == MessageType.STICKER else caption
    )
    message_id = client_message_id or uuid4()
    existing = db.scalar(
        select(Message).where(
            Message.id == message_id,
            Message.tenant_id == context.tenant_id,
            Message.conversation_id == conversation_id,
        )
    )
    if existing is not None:
        existing_attachment = db.scalar(
            select(MessageAttachment).where(
                MessageAttachment.tenant_id == context.tenant_id,
                MessageAttachment.message_id == existing.id,
            )
        )
        same_content = bool(
            existing_attachment
            and (
                existing_attachment.content_sha256 == validated.content_sha256
                or (
                    existing_attachment.content_sha256 is None
                    and existing_attachment.size_bytes == len(content)
                    and existing_attachment.file_name == file_name
                )
            )
        )
        if (
            existing.direction == MessageDirection.OUTGOING
            and existing.message_type == validated.message_type
            and existing.sender_user_id == context.user.id
            and existing.body == normalized_caption
            and existing.reply_to_message_id == reply_to_message_id
            and same_content
        ):
            if existing.status == MessageStatus.PENDING:
                delivery = ensure_delivery(db, existing)
                db.commit()
                await asyncio.to_thread(
                    dispatch_delivery,
                    delivery.id,
                    context.tenant_id,
                )
            return message_response(
                db,
                context.tenant_id,
                existing,
                attachments=[existing_attachment],
            )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Identificador de mensagem já utilizado",
        )

    stored = await LocalStorageProvider().save(
        str(context.tenant_id), file_name, content
    )
    created_at = datetime.now(UTC)
    message = Message(
        id=message_id,
        tenant_id=context.tenant_id,
        conversation_id=conversation_id,
        sender_user_id=context.user.id,
        sender_name=normalized_sender_name(context.user.name),
        reply_to_message_id=reply_to.id if reply_to else None,
        reply_to_provider_message_id=reply_to.provider_message_id if reply_to else None,
        direction=MessageDirection.OUTGOING,
        message_type=validated.message_type,
        status=MessageStatus.PENDING,
        body=normalized_caption,
        attempt_count=0,
    )
    db.add(message)
    conversation.last_message_at = created_at
    db.flush()
    db.add(
        MessageAttachment(
            tenant_id=context.tenant_id,
            message_id=message.id,
            file_name=file_name,
            content_type=validated.content_type,
            size_bytes=stored.size_bytes,
            content_sha256=validated.content_sha256,
            storage_key=stored.key,
            public_url=stored.public_url,
        )
    )
    delivery = create_delivery(
        tenant_id=context.tenant_id,
        message_id=message.id,
        now=created_at,
    )
    db.add(delivery)
    db.commit()
    db.refresh(message)
    await realtime_manager.broadcast(
        context.tenant_id,
        "message.created",
        {
            **message_response(
                db,
                context.tenant_id,
                message,
            ).model_dump(mode="json"),
            "channel_id": str(conversation.channel_id),
        },
    )
    await asyncio.to_thread(
        dispatch_delivery,
        delivery.id,
        context.tenant_id,
    )
    return message_response(db, context.tenant_id, message, reply_to)


@router.post(
    "/conversations/{conversation_id}/messages/{message_id}/retry",
    response_model=MessageResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def retry_message(
    conversation_id: UUID,
    message_id: UUID,
    context: AuthContext = Depends(get_auth_context),
    db: Session = Depends(get_db),
) -> MessageResponse:
    conversation, _, _ = conversation_delivery_context(
        db,
        context,
        conversation_id,
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
    conversation.last_message_at = attempted_at
    delivery = ensure_delivery(db, message, reset=True)
    db.commit()
    db.refresh(message)
    await realtime_manager.broadcast(
        context.tenant_id,
        "message.updated",
        {
            **message_response(
                db,
                context.tenant_id,
                message,
            ).model_dump(mode="json"),
            "channel_id": str(conversation.channel_id),
        },
    )
    await asyncio.to_thread(
        dispatch_delivery,
        delivery.id,
        context.tenant_id,
    )
    return message_response(db, context.tenant_id, message)
