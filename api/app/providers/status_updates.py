from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.channels.models import WhatsAppChannel
from app.common.enums import MessageDirection, MessageStatus
from app.conversations.models import Conversation
from app.messages.models import Message
from app.providers.base import IgnoredWebhookEvent, MessageStatusUpdateResult
from app.providers.factory import get_provider
from app.providers.models import ProviderEvent

STATUS_ORDER = {
    MessageStatus.PENDING: 0,
    MessageStatus.SENT: 1,
    MessageStatus.DELIVERED: 2,
    MessageStatus.READ: 3,
}


@dataclass
class StatusApplication:
    matched_ids: set[str]
    changed_messages: list[Message]

    def covers(self, provider_message_ids: list[str]) -> bool:
        return set(provider_message_ids).issubset(self.matched_ids)


def can_advance_message_status(current: MessageStatus, target: MessageStatus) -> bool:
    """Only move a successful outgoing delivery forward; failed is terminal here."""
    if current == MessageStatus.FAILED or target not in STATUS_ORDER:
        return False
    return STATUS_ORDER.get(target, -1) > STATUS_ORDER.get(current, -1)


def apply_message_status_update(
    db: Session,
    *,
    tenant_id: UUID,
    channel_id: UUID,
    update: MessageStatusUpdateResult,
) -> StatusApplication:
    messages = list(
        db.scalars(
            select(Message)
            .join(Conversation, Conversation.id == Message.conversation_id)
            .where(
                Message.tenant_id == tenant_id,
                Conversation.tenant_id == tenant_id,
                Conversation.channel_id == channel_id,
                Message.direction == MessageDirection.OUTGOING,
                Message.provider_message_id.in_(update.provider_message_ids),
            )
        )
    )
    changed: list[Message] = []
    for message in messages:
        changed_message = False
        receipt_at = update.timestamp or datetime.now(UTC)
        if can_advance_message_status(message.status, update.status):
            message.status = update.status
            message.error = None
            changed_message = True
        if update.status in {MessageStatus.DELIVERED, MessageStatus.READ}:
            if message.delivered_at is None:
                message.delivered_at = receipt_at
                changed_message = True
        if update.status == MessageStatus.READ and message.read_at is None:
            message.read_at = receipt_at
            changed_message = True
        if changed_message:
            changed.append(message)
    return StatusApplication(
        matched_ids={
            message.provider_message_id for message in messages if message.provider_message_id
        },
        changed_messages=changed,
    )


def reconcile_pending_status_events(
    db: Session,
    *,
    channel: WhatsAppChannel,
    provider_message_id: str | None,
) -> list[Message]:
    """Apply receipts that won the race against the synchronous send confirmation."""
    if not provider_message_id:
        return []

    adapter = get_provider(channel.provider, channel, db)
    events = list(
        db.scalars(
            select(ProviderEvent)
            .where(
                ProviderEvent.tenant_id == channel.tenant_id,
                ProviderEvent.channel_id == channel.id,
                ProviderEvent.processed.is_(False),
            )
            .order_by(ProviderEvent.created_at)
        )
    )
    changed_by_id: dict[UUID, Message] = {}
    for event in events:
        try:
            update = adapter.handle_message_status(event.payload)
        except (IgnoredWebhookEvent, ValueError):
            continue
        if update is None or provider_message_id not in update.provider_message_ids:
            continue
        application = apply_message_status_update(
            db,
            tenant_id=channel.tenant_id,
            channel_id=channel.id,
            update=update,
        )
        if application.covers(update.provider_message_ids):
            event.processed = True
            event.processing_error = None
        for message in application.changed_messages:
            changed_by_id[message.id] = message
    return list(changed_by_id.values())
