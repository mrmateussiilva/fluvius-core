from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.attachments.service import (
    IncomingAttachmentStorageError,
    StagedIncomingAttachment,
    persist_incoming_attachment,
    stage_incoming_attachment,
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
from app.config import settings
from app.contacts.models import Contact
from app.contacts.naming import usable_contact_name
from app.contacts.service import (
    needs_group_profile_import,
    synchronize_contact_profile,
)
from app.conversations.models import Conversation
from app.database import get_db
from app.messages.models import Message, MessageContactShare, MessageRevision
from app.providers.base import (
    IgnoredWebhookEvent,
    IncomingMessageEditResult,
    IncomingMessageResult,
    WhatsAppProvider,
)
from app.providers.evolution_credentials import (
    ProviderConfigurationError,
    claim_evolution_credential,
)
from app.providers.factory import get_provider
from app.providers.inbox_dispatcher import dispatch_provider_event_inbox
from app.providers.models import ProviderEvent, ProviderEventInbox
from app.providers.pending_events import (
    PENDING_EDIT_ERROR,
    PENDING_INCOMING_MESSAGE_ERROR,
    PENDING_RECEIPT_ERROR,
)
from app.providers.status_updates import apply_message_status_update
from app.realtime.manager import realtime_manager
from app.storage.local import LocalStorageProvider

router = APIRouter(prefix="/webhooks", tags=["webhooks"])
EDIT_CONTENT_UNAVAILABLE = (
    "O WhatsApp informou a edição, mas o provider não disponibilizou o novo texto"
)


def reopen_from_provider(conversation: Conversation) -> bool:
    if conversation.status != ConversationStatus.CLOSED:
        return False
    conversation.status = ConversationStatus.NEW
    conversation.assigned_user_id = None
    return True


def lock_provider_thread(
    db: Session,
    *,
    tenant_id: UUID,
    channel_id: UUID,
    thread_number: str,
) -> None:
    lock_key = f"{tenant_id}:{channel_id}:{thread_number}"
    db.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:lock_key, 0))"),
        {"lock_key": lock_key},
    )


def apply_message_edit(
    db: Session,
    *,
    channel: WhatsAppChannel,
    event: ProviderEvent,
    edit: IncomingMessageEditResult,
) -> Message | None:
    message = db.scalar(
        select(Message)
        .join(
            Conversation,
            (Conversation.id == Message.conversation_id)
            & (Conversation.tenant_id == Message.tenant_id),
        )
        .where(
            Message.tenant_id == channel.tenant_id,
            Message.provider_message_id == edit.target_provider_message_id,
            Conversation.tenant_id == channel.tenant_id,
            Conversation.channel_id == channel.id,
        )
        .with_for_update()
    )
    if message is None:
        return None

    revision = db.scalar(
        select(MessageRevision).where(
            MessageRevision.tenant_id == channel.tenant_id,
            MessageRevision.provider_event_id == edit.provider_event_id,
        )
    )
    if revision is None:
        revision = MessageRevision(
            tenant_id=channel.tenant_id,
            message_id=message.id,
            provider_event_id=edit.provider_event_id,
            previous_body=message.body,
            body=edit.body,
            content_available=edit.body is not None,
            edited_at=edit.timestamp,
        )
        db.add(revision)

    message.edited_at = edit.timestamp
    if edit.body is None:
        message.edit_content_unavailable = True
        event.processing_error = EDIT_CONTENT_UNAVAILABLE
    else:
        message.body = edit.body
        message.edit_content_unavailable = False
        event.processing_error = None
    event.processed = True
    db.flush()
    return message


async def _accept_message_event(
    *,
    db: Session,
    channel: WhatsAppChannel,
    provider_adapter: WhatsAppProvider,
    event_type: str,
    event_id: str | None,
    payload: dict,
    sanitized_payload: dict,
) -> dict[str, str]:
    event = _find_provider_event(
        db,
        tenant_id=channel.tenant_id,
        channel_id=channel.id,
        event_id=event_id,
    )
    if event is not None:
        if event.processed:
            return {"status": "duplicate"}
        existing_inbox = db.scalar(
            select(ProviderEventInbox).where(
                ProviderEventInbox.tenant_id == channel.tenant_id,
                ProviderEventInbox.provider_event_id == event.id,
            )
        )
        if existing_inbox is not None:
            dispatch_provider_event_inbox(existing_inbox.id, channel.tenant_id)
            return {"status": "accepted"}

    try:
        incoming = await provider_adapter.handle_webhook(payload)
    except IgnoredWebhookEvent:
        event = event or ProviderEvent(
            tenant_id=channel.tenant_id,
            channel_id=channel.id,
            provider=channel.provider.value,
            event_type=event_type,
            provider_event_id=str(event_id) if event_id else None,
            payload=sanitized_payload,
        )
        event.processed = True
        event.processing_error = None
        db.add(event)
        db.commit()
        return {"status": "ignored"}
    except (ValueError, NotImplementedError) as exc:
        event = event or ProviderEvent(
            tenant_id=channel.tenant_id,
            channel_id=channel.id,
            provider=channel.provider.value,
            event_type=event_type,
            provider_event_id=str(event_id) if event_id else None,
            payload=sanitized_payload,
        )
        event.processing_error = str(exc)
        db.add(event)
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc

    staged = None
    media_error = None
    if isinstance(incoming, IncomingMessageResult):
        try:
            staged, media_error = await stage_incoming_attachment(
                tenant_id=channel.tenant_id,
                incoming=incoming,
            )
        except IncomingAttachmentStorageError as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Storage temporariamente indisponível para receber a mídia",
            ) from exc
        normalized_kind = "message"
    else:
        normalized_kind = "edit"
    normalized_payload = incoming.model_dump(
        mode="json",
        exclude={"media_base64", "raw_payload"},
    )

    event = event or ProviderEvent(
        tenant_id=channel.tenant_id,
        channel_id=channel.id,
        provider=channel.provider.value,
        event_type=event_type,
        provider_event_id=str(event_id) if event_id else None,
        payload=sanitized_payload,
    )
    inbox = None
    try:
        event.processing_error = PENDING_INCOMING_MESSAGE_ERROR
        db.add(event)
        db.flush()
        inbox = ProviderEventInbox(
            tenant_id=channel.tenant_id,
            provider_event_id=event.id,
            normalized_kind=normalized_kind,
            normalized_payload=normalized_payload,
            status="queued",
            next_attempt_at=datetime.now(UTC),
            media_storage_key=staged.storage_key if staged else None,
            media_file_name=staged.file_name if staged else None,
            media_content_type=staged.content_type if staged else None,
            media_size_bytes=staged.size_bytes if staged else None,
            media_content_sha256=staged.content_sha256 if staged else None,
            media_error=media_error,
        )
        db.add(inbox)
        db.commit()
    except IntegrityError:
        db.rollback()
        await _discard_staged_attachment(staged)
        duplicate = _find_provider_event(
            db,
            tenant_id=channel.tenant_id,
            channel_id=channel.id,
            event_id=event_id,
        )
        if duplicate is None:
            return {"status": "duplicate"}
        duplicate_inbox = db.scalar(
            select(ProviderEventInbox).where(
                ProviderEventInbox.tenant_id == channel.tenant_id,
                ProviderEventInbox.provider_event_id == duplicate.id,
            )
        )
        if duplicate_inbox is not None:
            dispatch_provider_event_inbox(duplicate_inbox.id, channel.tenant_id)
        return {"status": "duplicate"}
    except Exception:
        db.rollback()
        await _discard_staged_attachment(staged)
        raise

    if inbox is not None:
        dispatch_provider_event_inbox(inbox.id, channel.tenant_id)
    return {"status": "accepted"}


def _find_provider_event(
    db: Session,
    *,
    tenant_id: UUID,
    channel_id: UUID,
    event_id: str | None,
) -> ProviderEvent | None:
    if event_id is None:
        return None
    return db.scalar(
        select(ProviderEvent).where(
            ProviderEvent.tenant_id == tenant_id,
            ProviderEvent.channel_id == channel_id,
            ProviderEvent.provider_event_id == str(event_id),
        )
    )


async def _discard_staged_attachment(
    staged: StagedIncomingAttachment | None,
) -> None:
    if staged is not None:
        await LocalStorageProvider().delete(staged.storage_key)


@router.post("/whatsapp/{provider}/{channel_id}", status_code=status.HTTP_202_ACCEPTED)
async def whatsapp_webhook(
    provider: ChannelProvider,
    channel_id: UUID,
    payload: dict,
    x_webhook_secret: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> dict[str, str]:
    channel = db.scalar(
        select(WhatsAppChannel).where(
            WhatsAppChannel.id == channel_id, WhatsAppChannel.provider == provider
        )
    )
    if channel is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Canal não encontrado")

    try:
        if channel.provider == ChannelProvider.EVOLUTION_GO:
            claim_evolution_credential(db, channel)
        provider_adapter = get_provider(provider, channel, db)
    except ProviderConfigurationError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    if not provider_adapter.verify_webhook(payload, x_webhook_secret, settings.webhook_secret):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Webhook não autorizado",
        )

    event_type = str(payload.get("event") or payload.get("type") or "unknown")
    normalized_event = event_type.lower().replace("_", ".")
    event_id = provider_adapter.webhook_event_id(payload)
    sanitized_payload = provider_adapter.sanitize_webhook_payload(payload)
    if normalized_event == "message":
        return await _accept_message_event(
            db=db,
            channel=channel,
            provider_adapter=provider_adapter,
            event_type=event_type,
            event_id=event_id,
            payload=payload,
            sanitized_payload=sanitized_payload,
        )
    event = None
    if event_id is not None:
        event = db.scalar(
            select(ProviderEvent).where(
                ProviderEvent.tenant_id == channel.tenant_id,
                ProviderEvent.channel_id == channel.id,
                ProviderEvent.provider_event_id == str(event_id),
            )
        )
        if event is not None and event.processed:
            return {"status": "duplicate"}
    if event is None:
        event = ProviderEvent(
            tenant_id=channel.tenant_id,
            channel_id=channel.id,
            provider=provider.value,
            event_type=event_type,
            provider_event_id=str(event_id) if event_id else None,
            payload=sanitized_payload,
            processing_error=(
                PENDING_INCOMING_MESSAGE_ERROR
                if normalized_event == "message"
                else None
            ),
        )
        db.add(event)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            if event_id is None:
                return {"status": "duplicate"}
            event = db.scalar(
                select(ProviderEvent).where(
                    ProviderEvent.tenant_id == channel.tenant_id,
                    ProviderEvent.channel_id == channel.id,
                    ProviderEvent.provider_event_id == str(event_id),
                )
            )
            if event is None or event.processed:
                return {"status": "duplicate"}

    if normalized_event in {"connected", "disconnected", "loggedout"} or any(
        part in normalized_event for part in ("connection", "status", "qrcode")
    ):
        await _process_channel_status(channel, sanitized_payload, db)
        event.processed = True
        db.commit()
        return {"status": "accepted"}

    if normalized_event == "receipt":
        try:
            update = provider_adapter.handle_message_status(sanitized_payload)
            if update is None:
                event.processed = True
                db.commit()
                return {"status": "ignored"}
            application = apply_message_status_update(
                db,
                tenant_id=channel.tenant_id,
                channel_id=channel.id,
                update=update,
            )
            event.processed = application.covers(update.provider_message_ids)
            event.processing_error = (
                None
                if event.processed
                else PENDING_RECEIPT_ERROR
            )
            db.commit()
            for message in application.changed_messages:
                await realtime_manager.broadcast(
                    channel.tenant_id,
                    "message.updated",
                    {
                        "id": str(message.id),
                        "conversation_id": str(message.conversation_id),
                        "channel_id": str(channel.id),
                        "status": message.status.value,
                    },
                )
            return {"status": "accepted" if event.processed else "pending"}
        except IgnoredWebhookEvent:
            event.processed = True
            db.commit()
            return {"status": "ignored"}
        except ValueError as exc:
            event.processing_error = str(exc)
            db.commit()
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=str(exc),
            ) from exc

    try:
        incoming = await provider_adapter.handle_webhook(payload)
        if isinstance(incoming, IncomingMessageEditResult):
            edited_message = apply_message_edit(
                db,
                channel=channel,
                event=event,
                edit=incoming,
            )
            if edited_message is None:
                event.processing_error = (
                    PENDING_EDIT_ERROR
                )
                db.commit()
                return {"status": "pending"}
            db.commit()
            await realtime_manager.broadcast(
                channel.tenant_id,
                "message.updated",
                {
                    "id": str(edited_message.id),
                    "conversation_id": str(edited_message.conversation_id),
                    "channel_id": str(channel.id),
                    "edited_at": edited_message.edited_at.isoformat(),
                    "edit_content_unavailable": (
                        edited_message.edit_content_unavailable
                    ),
                },
            )
            return {"status": "accepted"}

        thread_number = (
            incoming.chat_id
            if incoming.is_group and incoming.chat_id
            else incoming.from_number
        )
        lock_provider_thread(
            db,
            tenant_id=channel.tenant_id,
            channel_id=channel.id,
            thread_number=thread_number,
        )
        db.refresh(event)
        if event.processed:
            db.commit()
            return {"status": "duplicate"}
        duplicate = db.scalar(
            select(Message).where(
                Message.tenant_id == channel.tenant_id,
                Message.provider_message_id == incoming.provider_message_id,
            )
        )
        if duplicate:
            event.processed = True
            event.processing_error = None
            db.commit()
            return {"status": "duplicate"}

        contact = db.scalar(
            select(Contact).where(
                Contact.tenant_id == channel.tenant_id,
                Contact.phone_number == thread_number,
            )
        )
        sender_name = usable_contact_name(incoming.sender_name, thread_number)
        if contact is None:
            group_label = (
                incoming.chat_name
                or (f"Grupo {thread_number[-6:]}" if incoming.is_group else None)
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
        if conversation is None:
            conversation = Conversation(
                tenant_id=channel.tenant_id,
                channel_id=channel.id,
                contact_id=contact.id,
                status=ConversationStatus.NEW,
                last_message_at=incoming.timestamp,
            )
            db.add(conversation)
            db.flush()
        else:
            reopened_conversation = reopen_from_provider(conversation)
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
        participant_phone = (
            incoming.participant_phone
            if incoming.is_group
            else None
        )
        participant_name = (
            incoming.participant_name or incoming.sender_name
            if incoming.is_group
            else None
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
            participant_phone=participant_phone,
            participant_name=participant_name,
            provider_message_id=incoming.provider_message_id,
            attempt_count=1 if incoming.direction == MessageDirection.OUTGOING else 0,
            last_attempt_at=(
                incoming.timestamp
                if incoming.direction == MessageDirection.OUTGOING
                else None
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
        _, media_error = await persist_incoming_attachment(
            db,
            tenant_id=channel.tenant_id,
            message=message,
            incoming=incoming,
        )
        if media_error:
            message.error = media_error
        reconciled_edits: list[Message] = []
        pending_events = list(
            db.scalars(
                select(ProviderEvent)
                .where(
                    ProviderEvent.tenant_id == channel.tenant_id,
                    ProviderEvent.channel_id == channel.id,
                    ProviderEvent.event_type.in_(["Message", "message"]),
                    ProviderEvent.processed.is_(False),
                    ProviderEvent.id != event.id,
                )
                .order_by(ProviderEvent.created_at)
            )
        )
        for pending_event in pending_events:
            try:
                pending_edit = await provider_adapter.handle_webhook(
                    pending_event.payload
                )
            except (IgnoredWebhookEvent, ValueError):
                continue
            if (
                isinstance(pending_edit, IncomingMessageEditResult)
                and pending_edit.target_provider_message_id
                == message.provider_message_id
            ):
                reconciled = apply_message_edit(
                    db,
                    channel=channel,
                    event=pending_event,
                    edit=pending_edit,
                )
                if reconciled is not None:
                    reconciled_edits.append(reconciled)
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
            except (ProviderConfigurationError, NotImplementedError, ValueError):
                pass

        event.processed = True
        event.processing_error = None
        db.commit()
        if created_conversation:
            await realtime_manager.broadcast(
                channel.tenant_id,
                "conversation.created",
                {
                    "id": str(conversation.id),
                    "channel_id": str(channel.id),
                },
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
            },
        )
        for reconciled in reconciled_edits:
            await realtime_manager.broadcast(
                channel.tenant_id,
                "message.updated",
                {
                    "id": str(reconciled.id),
                    "conversation_id": str(reconciled.conversation_id),
                    "channel_id": str(channel.id),
                    "edited_at": reconciled.edited_at.isoformat(),
                    "edit_content_unavailable": (
                        reconciled.edit_content_unavailable
                    ),
                },
            )
        return {"status": "accepted"}
    except IgnoredWebhookEvent:
        event.processed = True
        event.processing_error = None
        db.commit()
        return {"status": "ignored"}
    except (ValueError, NotImplementedError) as exc:
        event.processing_error = str(exc)
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc


async def _process_channel_status(channel: WhatsAppChannel, payload: dict, db: Session) -> None:
    event_name = str(payload.get("event") or payload.get("type") or "").lower()
    raw = str(
        payload.get("status")
        or payload.get("state")
        or payload.get("data", {}).get("state")
        or payload.get("data", {}).get("status")
        or ""
    )
    if "qr" in event_name:
        channel.status = ChannelStatus.REQUIRES_QR
    elif event_name == "connected":
        channel.status = ChannelStatus.CONNECTED
    elif event_name in {"disconnected", "loggedout"}:
        channel.status = ChannelStatus.DISCONNECTED
    elif raw:
        mapper = get_provider(channel.provider, channel, db)
        map_status = getattr(mapper, "_map_status", None)
        channel.status = map_status(raw) if map_status else ChannelStatus.DISCONNECTED
    await realtime_manager.broadcast(
        channel.tenant_id,
        "channel.status.updated",
        {
            "id": str(channel.id),
            "channel_id": str(channel.id),
            "status": channel.status,
        },
    )
