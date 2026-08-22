import asyncio
from datetime import UTC, datetime
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.attachments.models import MessageAttachment
from app.attachments.service import (
    MAX_MEDIA_BYTES,
    UnsupportedAttachmentError,
    attachment_content_url,
    validate_outgoing_attachment,
)
from app.auth.dependencies import AuthContext, get_auth_context
from app.channels.models import WhatsAppChannel
from app.common.enums import (
    ChannelProvider,
    ChannelStatus,
    ContactKind,
    MessageDirection,
    MessageStatus,
    MessageType,
)
from app.common.schemas import (
    MessageAttachmentResponse,
    MessageResponse,
    QuotedMessageResponse,
    SharedContactResponse,
)
from app.contacts.models import Contact
from app.contacts.naming import contact_display_name
from app.conversations.models import Conversation
from app.conversations.router import (
    ensure_conversation_assignee,
    get_accessible_conversation,
)
from app.database import get_db
from app.delivery.dispatcher import create_delivery, dispatch_delivery
from app.delivery.models import MessageDelivery
from app.delivery.service import normalized_sender_name
from app.messages.models import Message, MessageContactShare
from app.messages.schemas import ContactMessageCreate, MessageCreate
from app.providers.evolution_credentials import (
    ProviderConfigurationError,
    claim_evolution_credential,
)
from app.realtime.manager import realtime_manager
from app.storage.local import LocalStorageProvider
from app.users.channel_access import accessible_channel_ids

router = APIRouter(tags=["messages"])
OFFLINE_MESSAGE = "WhatsApp desconectado. Reconecte o canal antes de enviar mensagens."
MAX_MENTIONS = 50
MAX_CONTACT_REFERENCES = 50


def attachment_response(
    attachment: MessageAttachment,
) -> MessageAttachmentResponse:
    return MessageAttachmentResponse(
        id=attachment.id,
        file_name=attachment.file_name,
        content_type=attachment.content_type,
        size_bytes=attachment.size_bytes,
        public_url=attachment_content_url(attachment.id),
    )


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


def normalize_phone(value: str) -> str:
    return "".join(character for character in value if character.isdigit())


def is_mentionable_phone(value: str) -> bool:
    return 10 <= len(normalize_phone(value)) <= 15


def mention_jid(value: str | None) -> str | None:
    if not value:
        return None
    raw = str(value).strip()
    lower = raw.lower()
    if lower.endswith("@lid"):
        digits = normalize_phone(raw.split("@", 1)[0])
        return f"{digits}@lid" if digits else None
    if lower.endswith("@s.whatsapp.net"):
        digits = normalize_phone(raw.split("@", 1)[0])
        return f"{digits}@s.whatsapp.net" if is_mentionable_phone(digits) else None
    digits = normalize_phone(raw)
    if len(digits) > 15:
        return f"{digits}@lid"
    if is_mentionable_phone(digits):
        return f"{digits}@s.whatsapp.net"
    return None


def group_member_phones(contact: Contact) -> set[str]:
    phones: set[str] = set()
    if isinstance(contact.group_members, list):
        for item in contact.group_members:
            if not isinstance(item, dict):
                continue
            phone = normalize_phone(str(item.get("phone_number") or ""))
            if is_mentionable_phone(phone):
                phones.add(phone)
    return phones


def group_member_jids(contact: Contact) -> set[str]:
    jids: set[str] = set()
    if isinstance(contact.group_members, list):
        for item in contact.group_members:
            if not isinstance(item, dict):
                continue
            provider_jid = mention_jid(
                item.get("provider_jid")
                or item.get("jid")
                or item.get("JID")
                or item.get("lid")
                or item.get("LID")
            )
            if provider_jid:
                jids.add(provider_jid)
            phone = normalize_phone(str(item.get("phone_number") or ""))
            phone_jid = mention_jid(phone)
            if phone_jid:
                jids.add(phone_jid)
    return jids


def validate_message_mentions(
    contact: Contact,
    mentioned_phones: list[str] | None,
    mentioned_jids: list[str] | None,
) -> tuple[list[str], list[str]]:
    normalized: list[str] = []
    seen: set[str] = set()
    for value in mentioned_phones or []:
        phone = normalize_phone(value)
        if not is_mentionable_phone(phone) or phone in seen:
            continue
        seen.add(phone)
        normalized.append(phone)

    normalized_jids: list[str] = []
    seen_jids: set[str] = set()
    for value in mentioned_jids or []:
        jid = mention_jid(value)
        if not jid or jid in seen_jids:
            continue
        seen_jids.add(jid)
        normalized_jids.append(jid)
    if not normalized and not normalized_jids:
        return [], []
    if len(normalized) > MAX_MENTIONS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Marque no máximo {MAX_MENTIONS} participantes por mensagem.",
        )
    if len(normalized) + len(normalized_jids) > MAX_MENTIONS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Marque no máximo {MAX_MENTIONS} participantes por mensagem.",
        )
    if contact.kind != ContactKind.GROUP:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Menções só estão disponíveis em conversas de grupo.",
        )
    allowed_phones = group_member_phones(contact)
    allowed_jids = group_member_jids(contact)
    if not allowed_phones and not allowed_jids:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Atualize os dados do grupo antes de mencionar participantes.",
        )
    unknown = [phone for phone in normalized if phone not in allowed_phones]
    unknown_jids = [jid for jid in normalized_jids if jid not in allowed_jids]
    if unknown or unknown_jids:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Participante mencionado não pertence ao grupo sincronizado.",
        )
    return normalized, normalized_jids


def validate_referenced_contacts(
    db: Session,
    context: AuthContext,
    conversation_contact: Contact,
    referenced_contact_ids: list[UUID] | None,
) -> list[dict[str, str]]:
    unique_ids: list[UUID] = []
    seen: set[UUID] = set()
    for contact_id in referenced_contact_ids or []:
        if contact_id in seen:
            continue
        seen.add(contact_id)
        unique_ids.append(contact_id)
    if not unique_ids:
        return []
    if len(unique_ids) > MAX_CONTACT_REFERENCES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Referencie no máximo {MAX_CONTACT_REFERENCES} contatos por mensagem.",
        )
    if conversation_contact.kind != ContactKind.GROUP:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Referências a contatos só estão disponíveis em conversas de grupo.",
        )

    contacts = list(
        db.scalars(
            select(Contact).where(
                Contact.id.in_(unique_ids),
                Contact.tenant_id == context.tenant_id,
                Contact.kind == ContactKind.DIRECT,
            )
        )
    )
    contacts_by_id = {contact.id: contact for contact in contacts}
    missing = [contact_id for contact_id in unique_ids if contact_id not in contacts_by_id]
    if missing:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Contato referenciado não pertence ao tenant ou não é um contato direto.",
        )

    allowed_channel_ids = accessible_channel_ids(db, context)
    if allowed_channel_ids is not None:
        accessible_contacts = set(
            db.scalars(
                select(Conversation.contact_id).where(
                    Conversation.tenant_id == context.tenant_id,
                    Conversation.contact_id.in_(unique_ids),
                    Conversation.channel_id.in_(allowed_channel_ids),
                )
            )
        )
        blocked = [
            contact_id for contact_id in unique_ids if contact_id not in accessible_contacts
        ]
        if blocked:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Contato referenciado não encontrado",
            )

    return [
        {
            "contact_id": str(contact.id),
            "phone_number": contact.phone_number,
            "display_name": contact_display_name(contact),
        }
        for contact_id in unique_ids
        for contact in [contacts_by_id[contact_id]]
    ]


def message_response(
    db: Session,
    tenant_id: UUID,
    message: Message,
    reply_to: Message | None = None,
    attachments: list[MessageAttachment] | None = None,
    shared_contacts: list[MessageContactShare] | None = None,
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
            participant_name=reply_to.participant_name,
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
    if shared_contacts is None:
        shared_contacts = list(
            db.scalars(
                select(MessageContactShare)
                .where(
                    MessageContactShare.tenant_id == tenant_id,
                    MessageContactShare.message_id == message.id,
                )
                .order_by(MessageContactShare.position)
            )
        )
    return MessageResponse.model_validate(message).model_copy(
        update={
            "referenced_contacts": message.referenced_contacts or [],
            "reply_to": quoted,
            "attachments": [
                attachment_response(attachment)
                for attachment in attachments
            ],
            "shared_contacts": [
                SharedContactResponse.model_validate(shared_contact)
                for shared_contact in shared_contacts
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
    shared_contacts_by_message: dict[UUID, list[MessageContactShare]] = {}
    if messages:
        for attachment in db.scalars(
            select(MessageAttachment).where(
                MessageAttachment.tenant_id == tenant_id,
                MessageAttachment.message_id.in_([message.id for message in messages]),
            )
        ):
            attachments_by_message.setdefault(attachment.message_id, []).append(attachment)
        for shared_contact in db.scalars(
            select(MessageContactShare)
            .where(
                MessageContactShare.tenant_id == tenant_id,
                MessageContactShare.message_id.in_([message.id for message in messages]),
            )
            .order_by(MessageContactShare.message_id, MessageContactShare.position)
        ):
            shared_contacts_by_message.setdefault(
                shared_contact.message_id, []
            ).append(shared_contact)
    return [
        message_response(
            db,
            tenant_id,
            message,
            replies.get(message.reply_to_message_id),
            attachments_by_message.get(message.id, []),
            shared_contacts_by_message.get(message.id, []),
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
    limit: int = Query(default=100, ge=1, le=500),
    before: datetime | None = Query(default=None),
    context: AuthContext = Depends(get_auth_context),
    db: Session = Depends(get_db),
) -> list[MessageResponse]:
    get_accessible_conversation(db, context, conversation_id)
    query = select(Message).where(
        Message.tenant_id == context.tenant_id,
        Message.conversation_id == conversation_id,
    )
    if before is not None:
        query = query.where(Message.created_at < before)

    messages = list(
        db.scalars(
            query.order_by(Message.created_at.desc()).limit(limit)
        )
    )
    messages.reverse()
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
    conversation, _, contact = conversation_delivery_context(
        db,
        context,
        conversation_id,
    )
    mentioned_phones, mentioned_jids = validate_message_mentions(
        contact,
        payload.mentioned_phones,
        payload.mentioned_jids,
    )
    referenced_contacts = validate_referenced_contacts(
        db,
        context,
        contact,
        payload.referenced_contact_ids,
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
            and (existing.mentioned_phones or []) == mentioned_phones
            and (existing.mentioned_jids or []) == mentioned_jids
            and (existing.referenced_contacts or []) == referenced_contacts
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
        mentioned_phones=mentioned_phones,
        mentioned_jids=mentioned_jids,
        referenced_contacts=referenced_contacts,
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
    "/conversations/{conversation_id}/contacts",
    response_model=MessageResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def send_contact_message(
    conversation_id: UUID,
    payload: ContactMessageCreate,
    context: AuthContext = Depends(get_auth_context),
    db: Session = Depends(get_db),
) -> MessageResponse:
    conversation, _, _ = conversation_delivery_context(db, context, conversation_id)
    source_contact = None
    if payload.contact_id:
        if payload.display_name or payload.phone_number:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Informe contact_id ou os dados manuais do contato, não ambos.",
            )
        source_contact = db.scalar(
            select(Contact).where(
                Contact.id == payload.contact_id,
                Contact.tenant_id == context.tenant_id,
                Contact.kind == ContactKind.DIRECT,
            )
        )
        if source_contact is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Contato não encontrado.",
            )
        allowed_channel_ids = accessible_channel_ids(db, context)
        if allowed_channel_ids is not None:
            has_access = db.scalar(
                select(Conversation.id).where(
                    Conversation.tenant_id == context.tenant_id,
                    Conversation.contact_id == source_contact.id,
                    Conversation.channel_id.in_(allowed_channel_ids),
                )
            )
            if has_access is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Contato não encontrado.",
                )
        display_name = contact_display_name(source_contact)
        phone_number = source_contact.phone_number
    else:
        display_name = " ".join((payload.display_name or "").split())
        phone_number = "".join(
            character
            for character in (payload.phone_number or "")
            if character.isdigit()
        )
        if not display_name or not 10 <= len(phone_number) <= 15:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Informe nome e telefone válido para compartilhar o contato.",
            )
    organization = " ".join((payload.organization or "").split()) or None
    existing = db.scalar(
        select(Message).where(
            Message.id == payload.client_message_id,
            Message.tenant_id == context.tenant_id,
            Message.conversation_id == conversation_id,
        )
    )
    if existing is not None:
        existing_share = db.scalar(
            select(MessageContactShare).where(
                MessageContactShare.tenant_id == context.tenant_id,
                MessageContactShare.message_id == existing.id,
                MessageContactShare.position == 0,
            )
        )
        same_contact = bool(
            existing_share
            and (
                (
                    source_contact is not None
                    and existing_share.source_contact_id == source_contact.id
                    and existing_share.organization == organization
                )
                or (
                    source_contact is None
                    and existing_share.source_contact_id is None
                    and existing_share.display_name == display_name
                    and existing_share.phone_number == phone_number
                    and existing_share.organization == organization
                )
            )
        )
        if (
            existing.direction == MessageDirection.OUTGOING
            and existing.message_type == MessageType.CONTACT
            and existing.sender_user_id == context.user.id
            and existing.reply_to_message_id == payload.reply_to_message_id
            and same_contact
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
                shared_contacts=[existing_share],
            )
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
        message_type=MessageType.CONTACT,
        status=MessageStatus.PENDING,
        body=None,
        attempt_count=0,
    )
    db.add(message)
    conversation.last_message_at = created_at
    db.flush()
    shared_contact = MessageContactShare(
        tenant_id=context.tenant_id,
        message_id=message.id,
        source_contact_id=source_contact.id if source_contact else None,
        position=0,
        display_name=display_name,
        phone_number=phone_number,
        organization=organization,
    )
    db.add(shared_contact)
    delivery = create_delivery(
        tenant_id=context.tenant_id,
        message_id=message.id,
        now=created_at,
    )
    db.add(delivery)
    db.commit()
    db.refresh(message)
    response = message_response(
        db,
        context.tenant_id,
        message,
        reply_to,
        shared_contacts=[shared_contact],
    )
    await realtime_manager.broadcast(
        context.tenant_id,
        "message.created",
        {
            **response.model_dump(mode="json"),
            "channel_id": str(conversation.channel_id),
        },
    )
    await asyncio.to_thread(dispatch_delivery, delivery.id, context.tenant_id)
    return response


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
    mentioned_phones: list[str] | None = Form(default=None),
    mentioned_jids: list[str] | None = Form(default=None),
    referenced_contact_ids: list[UUID] | None = Form(default=None),
    client_message_id: UUID | None = Form(default=None),
    context: AuthContext = Depends(get_auth_context),
    db: Session = Depends(get_db),
) -> MessageResponse:
    conversation, _, contact = conversation_delivery_context(
        db,
        context,
        conversation_id,
    )
    normalized_mentions, normalized_mention_jids = validate_message_mentions(
        contact,
        mentioned_phones,
        mentioned_jids,
    )
    referenced_contacts = validate_referenced_contacts(
        db,
        context,
        contact,
        referenced_contact_ids,
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
            and (existing.mentioned_phones or []) == normalized_mentions
            and (existing.mentioned_jids or []) == normalized_mention_jids
            and (existing.referenced_contacts or []) == referenced_contacts
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
        mentioned_phones=normalized_mentions,
        mentioned_jids=normalized_mention_jids,
        referenced_contacts=referenced_contacts,
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
