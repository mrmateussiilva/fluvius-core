from datetime import UTC, datetime
from uuid import UUID
import asyncio

from sqlalchemy import select

from app.ai.models import ChannelAiConfig
from app.ai.service import execute_ai_turn
from app.attachments.service import (
    IncomingAttachmentStorageError,
    StagedIncomingAttachment,
    persist_staged_incoming_attachment,
)
from app.channels.models import WhatsAppChannel
from app.common.enums import (
    ChannelProvider,
    ChannelStatus,
    ContactKind,
    ConversationStatus,
    MessageDirection,
    MessageStatus,
)
from app.contacts.models import Contact
from app.contacts.naming import usable_contact_name
from app.contacts.service import needs_group_profile_import, synchronize_contact_profile
from app.conversations.models import Conversation
from app.database import SessionLocal
from app.messages.models import Message, MessageContactShare
from app.providers.base import IncomingMessageEditResult, IncomingMessageResult
from app.providers.evolution_credentials import claim_evolution_credential
from app.providers.models import ProviderEvent, ProviderEventInbox
from app.providers.pending_events import PENDING_EDIT_ERROR
from app.providers.webhook_router import (
    apply_message_edit,
    lock_provider_thread,
    reopen_from_provider,
)
from app.realtime.manager import realtime_manager


async def process_provider_event_inbox(
    *,
    inbox_id: UUID,
    tenant_id: UUID,
) -> bool:
    with SessionLocal() as db:
        inbox = db.scalar(
            select(ProviderEventInbox)
            .where(
                ProviderEventInbox.id == inbox_id,
                ProviderEventInbox.tenant_id == tenant_id,
            )
            .with_for_update()
        )
        if inbox is None:
            return False
        if inbox.status == "completed":
            return True
        if inbox.status != "processing":
            return False
        event = db.scalar(
            select(ProviderEvent).where(
                ProviderEvent.id == inbox.provider_event_id,
                ProviderEvent.tenant_id == tenant_id,
            )
        )
        if event is None:
            return False
        channel = db.scalar(
            select(WhatsAppChannel).where(
                WhatsAppChannel.id == event.channel_id,
                WhatsAppChannel.tenant_id == tenant_id,
                WhatsAppChannel.provider == event.provider,
            )
        )
        if channel is None:
            return False
        if channel.provider == ChannelProvider.EVOLUTION_GO:
            claim_evolution_credential(db, channel)

        if inbox.normalized_kind == "edit":
            edit = IncomingMessageEditResult.model_validate(inbox.normalized_payload)
            edited_message = apply_message_edit(
                db,
                channel=channel,
                event=event,
                edit=edit,
            )
            if edited_message is None:
                event.processing_error = PENDING_EDIT_ERROR
                _complete_inbox(inbox)
                db.commit()
                return True
            _complete_inbox(inbox)
            db.commit()
            await _broadcast_message_updated(channel, edited_message)
            return True

        incoming = IncomingMessageResult.model_validate(inbox.normalized_payload)
        return await _process_message(
            db=db,
            channel=channel,
            event=event,
            inbox=inbox,
            incoming=incoming,
        )


async def _process_message(
    *,
    db,
    channel: WhatsAppChannel,
    event: ProviderEvent,
    inbox: ProviderEventInbox,
    incoming: IncomingMessageResult,
) -> bool:
    thread_number = (
        incoming.chat_id if incoming.is_group and incoming.chat_id else incoming.from_number
    )
    lock_provider_thread(
        db,
        tenant_id=channel.tenant_id,
        channel_id=channel.id,
        thread_number=thread_number,
    )
    db.refresh(event)
    if event.processed:
        _complete_inbox(inbox)
        db.commit()
        return True

    duplicate = db.scalar(
        select(Message).where(
            Message.tenant_id == channel.tenant_id,
            Message.provider_message_id == incoming.provider_message_id,
        )
    )
    if duplicate:
        event.processed = True
        event.processing_error = None
        _complete_inbox(inbox)
        db.commit()
        return True

    contact = db.scalar(
        select(Contact).where(
            Contact.tenant_id == channel.tenant_id,
            Contact.phone_number == thread_number,
        )
    )
    sender_name = usable_contact_name(incoming.sender_name, thread_number)
    if contact is None:
        group_label = incoming.chat_name or (
            f"Grupo {thread_number[-6:]}" if incoming.is_group else None
        )
        contact = Contact(
            tenant_id=channel.tenant_id,
            kind=ContactKind.GROUP if incoming.is_group else ContactKind.DIRECT,
            phone_number=thread_number,
            provider_address=incoming.provider_address if incoming.is_group else None,
            name=group_label if incoming.is_group else None,
            push_name=None if incoming.is_group else sender_name,
        )
        db.add(contact)
        db.flush()
    else:
        if incoming.is_group:
            contact.kind = ContactKind.GROUP
            if incoming.provider_address:
                contact.provider_address = incoming.provider_address
            if incoming.chat_name and not contact.name:
                contact.name = incoming.chat_name
        elif sender_name:
            contact.push_name = sender_name

    conversation = db.scalar(
        select(Conversation)
        .where(
            Conversation.tenant_id == channel.tenant_id,
            Conversation.channel_id == channel.id,
            Conversation.contact_id == contact.id,
        )
        .order_by(
            Conversation.last_message_at.desc().nullslast(),
            Conversation.created_at.desc(),
        )
    )
    created_conversation = conversation is None
    reopened_conversation = False
    ai_cfg = db.scalar(
        select(ChannelAiConfig).where(
            ChannelAiConfig.tenant_id == channel.tenant_id,
            ChannelAiConfig.channel_id == channel.id,
        )
    )
    should_activate_bot = bool(ai_cfg and ai_cfg.is_enabled and not incoming.is_group)

    if conversation is None:
        conversation = Conversation(
            tenant_id=channel.tenant_id,
            channel_id=channel.id,
            contact_id=contact.id,
            status=ConversationStatus.NEW,
            is_bot_active=should_activate_bot,
            last_message_at=incoming.timestamp,
        )
        db.add(conversation)
        db.flush()
    else:
        reopened_conversation = reopen_from_provider(conversation)
        if (
            reopened_conversation
            and conversation.assigned_user_id is None
            and should_activate_bot
        ):
            conversation.is_bot_active = True
        conversation.last_message_at = incoming.timestamp

    reply_to = None
    if incoming.reply_to_provider_message_id:
        reply_to = db.scalar(
            select(Message).where(
                Message.tenant_id == channel.tenant_id,
                Message.conversation_id == conversation.id,
                Message.provider_message_id == incoming.reply_to_provider_message_id,
            )
        )
    participant_name = (
        incoming.participant_name or incoming.sender_name if incoming.is_group else None
    )
    message = Message(
        tenant_id=channel.tenant_id,
        conversation_id=conversation.id,
        reply_to_message_id=reply_to.id if reply_to else None,
        reply_to_provider_message_id=incoming.reply_to_provider_message_id,
        direction=incoming.direction,
        message_type=incoming.message_type,
        status=(
            MessageStatus.SENT
            if incoming.direction == MessageDirection.OUTGOING
            else MessageStatus.DELIVERED
        ),
        body=incoming.body,
        sender_name=(
            participant_name
            if incoming.direction == MessageDirection.INCOMING and incoming.is_group
            else incoming.sender_name
        ),
        participant_phone=incoming.participant_phone if incoming.is_group else None,
        participant_name=participant_name,
        provider_message_id=incoming.provider_message_id,
        attempt_count=1 if incoming.direction == MessageDirection.OUTGOING else 0,
        last_attempt_at=(
            incoming.timestamp if incoming.direction == MessageDirection.OUTGOING else None
        ),
        sent_at=incoming.timestamp,
    )
    db.add(message)
    db.flush()
    for position, shared_contact in enumerate(incoming.shared_contacts):
        db.add(
            MessageContactShare(
                tenant_id=channel.tenant_id,
                message_id=message.id,
                position=position,
                display_name=shared_contact.display_name,
                phone_number=shared_contact.phone_number,
                organization=shared_contact.organization,
            )
        )

    media_error = inbox.media_error
    staged = _staged_attachment(inbox)
    if staged is not None:
        _, staged_error = await persist_staged_incoming_attachment(
            db,
            tenant_id=channel.tenant_id,
            message=message,
            staged=staged,
        )
        if staged_error:
            raise IncomingAttachmentStorageError(staged_error)
    if media_error:
        message.error = media_error

    reconciled_edits = _reconcile_pending_edits(
        db,
        channel=channel,
        message=message,
    )
    group_profile_updated = False
    if (
        contact.kind == ContactKind.GROUP
        and channel.status == ChannelStatus.CONNECTED
        and needs_group_profile_import(contact)
    ):
        try:
            await synchronize_contact_profile(
                db,
                channel=channel,
                contact=contact,
            )
            group_profile_updated = True
        except (ValueError, NotImplementedError):
            pass

    event.processed = True
    event.processing_error = None
    _complete_inbox(inbox)
    db.commit()

    if created_conversation:
        await realtime_manager.broadcast(
            channel.tenant_id,
            "conversation.created",
            {"id": str(conversation.id), "channel_id": str(channel.id)},
        )
    elif reopened_conversation:
        await realtime_manager.broadcast(
            channel.tenant_id,
            "conversation.updated",
            {
                "id": str(conversation.id),
                "channel_id": str(channel.id),
                "status": conversation.status.value,
            },
        )
    if group_profile_updated:
        await realtime_manager.broadcast(
            channel.tenant_id,
            "contact.updated",
            {"id": str(contact.id), "channel_id": str(channel.id)},
        )
        await realtime_manager.broadcast(
            channel.tenant_id,
            "conversation.updated",
            {
                "id": str(conversation.id),
                "channel_id": str(channel.id),
                "status": conversation.status.value,
            },
        )
    await realtime_manager.broadcast(
        channel.tenant_id,
        "message.created",
        {
            "id": str(message.id),
            "conversation_id": str(conversation.id),
            "channel_id": str(channel.id),
            "direction": message.direction.value,
        },
    )
    for reconciled in reconciled_edits:
        await _broadcast_message_updated(channel, reconciled)

    if (
        conversation.is_bot_active
        and incoming.direction == MessageDirection.INCOMING
        and not incoming.is_group
        and conversation.assigned_user_id is None
        and conversation.status == ConversationStatus.NEW
    ):
        asyncio.create_task(
            execute_ai_turn(
                db=SessionLocal(),
                tenant_id=channel.tenant_id,
                conversation_id=conversation.id,
            )
        )

    return True


def _reconcile_pending_edits(
    db,
    *,
    channel: WhatsAppChannel,
    message: Message,
) -> list[Message]:
    rows = db.execute(
        select(ProviderEvent, ProviderEventInbox)
        .join(
            ProviderEventInbox,
            (ProviderEventInbox.provider_event_id == ProviderEvent.id)
            & (ProviderEventInbox.tenant_id == channel.tenant_id),
        )
        .where(
            ProviderEvent.tenant_id == channel.tenant_id,
            ProviderEvent.channel_id == channel.id,
            ProviderEvent.processed.is_(False),
            ProviderEvent.processing_error == PENDING_EDIT_ERROR,
            ProviderEventInbox.tenant_id == channel.tenant_id,
            ProviderEventInbox.normalized_kind == "edit",
        )
        .order_by(ProviderEvent.created_at)
    ).all()
    reconciled_edits: list[Message] = []
    for pending_event, pending_inbox in rows:
        edit = IncomingMessageEditResult.model_validate(pending_inbox.normalized_payload)
        if edit.target_provider_message_id != message.provider_message_id:
            continue
        reconciled = apply_message_edit(
            db,
            channel=channel,
            event=pending_event,
            edit=edit,
        )
        if reconciled is not None:
            reconciled_edits.append(reconciled)
    return reconciled_edits


def _staged_attachment(
    inbox: ProviderEventInbox,
) -> StagedIncomingAttachment | None:
    values = (
        inbox.media_storage_key,
        inbox.media_file_name,
        inbox.media_content_type,
        inbox.media_size_bytes,
        inbox.media_content_sha256,
    )
    if not all(value is not None for value in values):
        return None
    return StagedIncomingAttachment(
        storage_key=inbox.media_storage_key or "",
        file_name=inbox.media_file_name or "",
        content_type=inbox.media_content_type or "",
        size_bytes=inbox.media_size_bytes or 0,
        content_sha256=inbox.media_content_sha256 or "",
    )


def _complete_inbox(inbox: ProviderEventInbox) -> None:
    inbox.status = "completed"
    inbox.completed_at = datetime.now(UTC)
    inbox.next_attempt_at = None
    inbox.locked_at = None
    inbox.rq_job_id = None
    inbox.last_error = None


async def _broadcast_message_updated(
    channel: WhatsAppChannel,
    message: Message,
) -> None:
    await realtime_manager.broadcast(
        channel.tenant_id,
        "message.updated",
        {
            "id": str(message.id),
            "conversation_id": str(message.conversation_id),
            "channel_id": str(channel.id),
            "edited_at": message.edited_at.isoformat() if message.edited_at else None,
            "edit_content_unavailable": message.edit_content_unavailable,
        },
    )
