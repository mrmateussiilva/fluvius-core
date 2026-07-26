from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.attachments.service import persist_incoming_attachment
from app.channels.models import WhatsAppChannel
from app.common.enums import (
    ChannelProvider,
    ChannelStatus,
    ConversationStatus,
    MessageDirection,
    MessageStatus,
)
from app.config import settings
from app.contacts.models import Contact
from app.conversations.models import Conversation
from app.database import get_db
from app.messages.models import Message, MessageRevision
from app.providers.base import (
    IgnoredWebhookEvent,
    IncomingMessageEditResult,
)
from app.providers.evolution_credentials import (
    ProviderConfigurationError,
    claim_evolution_credential,
)
from app.providers.factory import get_provider
from app.providers.models import ProviderEvent
from app.providers.status_updates import apply_message_status_update
from app.realtime.manager import realtime_manager

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
        provider_adapter = get_provider(provider, channel)
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
    event_id = provider_adapter.webhook_event_id(payload)
    sanitized_payload = provider_adapter.sanitize_webhook_payload(payload)
    event = ProviderEvent(
        tenant_id=channel.tenant_id,
        channel_id=channel.id,
        provider=provider.value,
        event_type=event_type,
        provider_event_id=str(event_id) if event_id else None,
        payload=sanitized_payload,
    )
    db.add(event)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        return {"status": "duplicate"}

    normalized_event = event_type.lower().replace("_", ".")
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
                else "Aguardando a mensagem correspondente ser confirmada pelo provider"
            )
            db.commit()
            for message in application.changed_messages:
                await realtime_manager.broadcast(
                    channel.tenant_id,
                    "message.updated",
                    {
                        "id": str(message.id),
                        "conversation_id": str(message.conversation_id),
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
                    "Aguardando a mensagem original da edição ser persistida"
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
                    "edited_at": edited_message.edited_at.isoformat(),
                    "edit_content_unavailable": (
                        edited_message.edit_content_unavailable
                    ),
                },
            )
            return {"status": "accepted"}

        duplicate = db.scalar(
            select(Message).where(
                Message.tenant_id == channel.tenant_id,
                Message.provider_message_id == incoming.provider_message_id,
            )
        )
        if duplicate:
            event.processed = True
            db.commit()
            return {"status": "duplicate"}

        contact = db.scalar(
            select(Contact).where(
                Contact.tenant_id == channel.tenant_id,
                Contact.phone_number == incoming.from_number,
            )
        )
        if contact is None:
            contact = Contact(
                tenant_id=channel.tenant_id,
                phone_number=incoming.from_number,
                name=incoming.sender_name,
                push_name=incoming.sender_name,
            )
            db.add(contact)
            db.flush()
        elif incoming.sender_name:
            contact.push_name = incoming.sender_name
            if not contact.name:
                contact.name = incoming.sender_name

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
        event.processed = True
        db.commit()
        if created_conversation:
            await realtime_manager.broadcast(
                channel.tenant_id, "conversation.created", {"id": str(conversation.id)}
            )
        elif reopened_conversation:
            await realtime_manager.broadcast(
                channel.tenant_id,
                "conversation.updated",
                {"id": str(conversation.id), "status": conversation.status.value},
            )
        await realtime_manager.broadcast(
            channel.tenant_id,
            "message.created",
            {"id": str(message.id), "conversation_id": str(conversation.id)},
        )
        for reconciled in reconciled_edits:
            await realtime_manager.broadcast(
                channel.tenant_id,
                "message.updated",
                {
                    "id": str(reconciled.id),
                    "conversation_id": str(reconciled.conversation_id),
                    "edited_at": reconciled.edited_at.isoformat(),
                    "edit_content_unavailable": (
                        reconciled.edit_content_unavailable
                    ),
                },
            )
        return {"status": "accepted"}
    except IgnoredWebhookEvent:
        event.processed = True
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
        mapper = get_provider(channel.provider, channel)
        map_status = getattr(mapper, "_map_status", None)
        channel.status = map_status(raw) if map_status else ChannelStatus.DISCONNECTED
    await realtime_manager.broadcast(
        channel.tenant_id,
        "channel.status.updated",
        {"id": str(channel.id), "status": channel.status},
    )
