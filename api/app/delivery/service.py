from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.attachments.models import MessageAttachment
from app.channels.models import WhatsAppChannel
from app.common.enums import MessageDirection, MessageStatus, MessageType
from app.contacts.models import Contact
from app.messages.models import Message
from app.providers.base import SendResult
from app.providers.factory import get_provider
from app.providers.status_updates import reconcile_pending_status_events
from app.storage.local import LocalStorageProvider


def normalized_sender_name(value: str | None) -> str | None:
    normalized = " ".join((value or "").split())
    return normalized or None


def format_outgoing_content(
    sender_name: str | None,
    content: str | None,
) -> str | None:
    if not content:
        return content
    normalized_name = normalized_sender_name(sender_name)
    if not normalized_name:
        return content
    return f"*{normalized_name}:*\n{content}"


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
    message.error = (
        result.error or "Provider não confirmou o envio com um identificador"
    )
    message.sent_at = None


async def call_provider(
    db: Session,
    *,
    message: Message,
    channel: WhatsAppChannel,
    contact: Contact,
) -> SendResult:
    reply_to = None
    if message.reply_to_message_id:
        reply_to = db.scalar(
            select(Message).where(
                Message.id == message.reply_to_message_id,
                Message.tenant_id == message.tenant_id,
                Message.conversation_id == message.conversation_id,
            )
        )
        if reply_to is None or not reply_to.provider_message_id:
            return SendResult(
                success=False,
                error="A mensagem citada não está disponível para envio.",
            )

    provider = get_provider(channel.provider, channel, db)
    participant = None
    if reply_to:
        participant = (
            contact.phone_number
            if reply_to.direction == MessageDirection.INCOMING
            else channel.phone_number or contact.phone_number
        )

    if message.message_type == MessageType.TEXT:
        return await provider.send_text(
            channel,
            contact.phone_number,
            format_outgoing_content(message.sender_name, message.body) or "",
            reply_to_provider_message_id=(
                reply_to.provider_message_id if reply_to else None
            ),
            reply_to_participant=participant,
            idempotency_key=str(message.id),
        )

    attachment = db.scalar(
        select(MessageAttachment).where(
            MessageAttachment.tenant_id == message.tenant_id,
            MessageAttachment.message_id == message.id,
        )
    )
    if attachment is None:
        return SendResult(
            success=False,
            error="Anexo da mensagem não foi encontrado.",
        )
    return await provider.send_media(
        channel,
        contact.phone_number,
        LocalStorageProvider().public_url_for(attachment.storage_key),
        (
            None
            if message.message_type == MessageType.STICKER
            else format_outgoing_content(message.sender_name, message.body)
        ),
        reply_to_provider_message_id=(
            reply_to.provider_message_id if reply_to else None
        ),
        reply_to_participant=participant,
        idempotency_key=str(message.id),
    )


def reconcile_delivery_receipts(
    db: Session,
    *,
    channel: WhatsAppChannel,
    message: Message,
) -> list[Message]:
    db.flush()
    return reconcile_pending_status_events(
        db,
        channel=channel,
        provider_message_id=message.provider_message_id,
    )


def safe_delivery_error(value: str | None, fallback: str) -> str:
    normalized = " ".join((value or "").split())
    return (normalized or fallback)[:500]
