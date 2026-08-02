from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth.dependencies import AuthContext, get_auth_context
from app.channels.models import WhatsAppChannel
from app.common.audit_models import AuditLog
from app.common.enums import ChannelStatus, ContactKind, ConversationStatus
from app.contacts.models import Contact
from app.contacts.schemas import (
    ContactCreateRequest,
    ContactListItem,
    ContactListResponse,
    ContactRefreshRequest,
    ContactResponse,
    ContactSearchResponse,
    ContactStartConversationRequest,
    ContactUpdateRequest,
)
from app.contacts.service import synchronize_contact_profile
from app.conversations.models import Conversation
from app.conversations.router import as_response as conversation_response
from app.conversations.router import conversation_query
from app.conversations.schemas import ConversationResponse
from app.database import get_db
from app.messages.models import Message
from app.providers.evolution_credentials import ProviderConfigurationError
from app.realtime.manager import realtime_manager
from app.users.channel_access import accessible_channel_ids, ensure_channel_access

router = APIRouter(prefix="/contacts", tags=["contacts"])
OFFLINE_MESSAGE = "WhatsApp desconectado. Reconecte o canal antes de atualizar o contato."


def normalize_phone(value: str) -> str:
    return "".join(character for character in value if character.isdigit())


def normalize_contact_name(value: str | None) -> str | None:
    normalized = " ".join((value or "").strip().split())
    return normalized or None


def validate_direct_phone(value: str) -> str:
    phone = normalize_phone(value)
    if not 10 <= len(phone) <= 15:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Informe um telefone com DDI e DDD.",
        )
    return phone


def display_name_for(contact: Contact) -> str:
    return (
        contact.name
        or contact.push_name
        or contact.business_name
        or contact.verified_name
        or contact.phone_number
    )


def is_mentionable_phone(value: str) -> bool:
    return 10 <= len(normalize_phone(value)) <= 15


def mention_jid(value: str | None) -> str | None:
    if not value:
        return None
    raw = value.strip()
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
    if 10 <= len(digits) <= 15:
        return f"{digits}@s.whatsapp.net"
    return None


def get_tenant_contact(db: Session, tenant_id: UUID, contact_id: UUID) -> Contact:
    contact = db.scalar(
        select(Contact).where(Contact.id == contact_id, Contact.tenant_id == tenant_id)
    )
    if contact is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Contato não encontrado")
    return contact


def visible_contact_statement(context: AuthContext, db: Session):
    statement = select(Contact).where(
        Contact.tenant_id == context.tenant_id,
        Contact.kind == ContactKind.DIRECT,
    )
    allowed_channel_ids = accessible_channel_ids(db, context)
    if allowed_channel_ids is not None:
        has_any_conversation = (
            select(Conversation.id)
            .where(
                Conversation.tenant_id == context.tenant_id,
                Conversation.contact_id == Contact.id,
            )
            .exists()
        )
        has_accessible_conversation = (
            select(Conversation.id)
            .where(
                Conversation.tenant_id == context.tenant_id,
                Conversation.contact_id == Contact.id,
                Conversation.channel_id.in_(allowed_channel_ids),
            )
            .exists()
        )
        statement = statement.where(
            or_(has_accessible_conversation, ~has_any_conversation)
        )
    return statement


def can_access_contact(db: Session, context: AuthContext, contact: Contact) -> bool:
    allowed_channel_ids = accessible_channel_ids(db, context)
    if allowed_channel_ids is None:
        return True
    has_any_conversation = db.scalar(
        select(Conversation.id).where(
            Conversation.tenant_id == context.tenant_id,
            Conversation.contact_id == contact.id,
        )
    )
    if has_any_conversation is None:
        return True
    has_accessible_conversation = db.scalar(
        select(Conversation.id).where(
            Conversation.tenant_id == context.tenant_id,
            Conversation.contact_id == contact.id,
            Conversation.channel_id.in_(allowed_channel_ids),
        )
    )
    return has_accessible_conversation is not None


def ensure_contact_access(db: Session, context: AuthContext, contact: Contact) -> None:
    if not can_access_contact(db, context, contact):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Contato não encontrado",
        )


def contact_list_item(
    db: Session,
    tenant_id: UUID,
    contact: Contact,
    *,
    allowed_channel_ids: set[UUID] | None = None,
) -> ContactListItem:
    stats_query = (
        select(
            func.count(Conversation.id),
            func.max(Message.created_at),
        )
        .select_from(Conversation)
        .join(
            Message,
            (Message.conversation_id == Conversation.id)
            & (Message.tenant_id == tenant_id),
            isouter=True,
        )
        .where(
            Conversation.tenant_id == tenant_id,
            Conversation.contact_id == contact.id,
        )
    )
    if allowed_channel_ids is not None:
        stats_query = stats_query.where(Conversation.channel_id.in_(allowed_channel_ids))
    conversation_count, last_interaction = db.execute(stats_query).one()
    return ContactListItem(
        id=contact.id,
        kind=contact.kind,
        display_name=display_name_for(contact),
        name=contact.name,
        phone_number=contact.phone_number,
        profile_picture_url=contact.profile_picture_url,
        is_on_whatsapp=contact.is_on_whatsapp,
        profile_synced_at=contact.profile_synced_at,
        conversation_count=conversation_count or 0,
        last_interaction_at=last_interaction,
        created_at=contact.created_at,
        updated_at=contact.updated_at,
    )


def contact_response(
    db: Session,
    tenant_id: UUID,
    contact: Contact,
    *,
    allowed_channel_ids: set[UUID] | None = None,
) -> ContactResponse:
    conversation_stats = select(
        func.count(Conversation.id),
        func.count(Conversation.id).filter(
            Conversation.status == ConversationStatus.CLOSED
        ),
    ).where(
        Conversation.tenant_id == tenant_id,
        Conversation.contact_id == contact.id,
    )
    if allowed_channel_ids is not None:
        conversation_stats = conversation_stats.where(
            Conversation.channel_id.in_(allowed_channel_ids)
        )
    conversation_count, closed_count = db.execute(
        conversation_stats
    ).one()
    interaction_query = (
        select(
            func.min(Message.created_at),
            func.max(Message.created_at),
        )
        .select_from(Message)
        .join(
            Conversation,
            (Conversation.id == Message.conversation_id)
            & (Conversation.tenant_id == tenant_id),
        )
        .where(
            Message.tenant_id == tenant_id,
            Conversation.tenant_id == tenant_id,
            Conversation.contact_id == contact.id,
        )
    )
    if allowed_channel_ids is not None:
        interaction_query = interaction_query.where(
            Conversation.channel_id.in_(allowed_channel_ids)
        )
    first_interaction, last_interaction = db.execute(interaction_query).one()
    display_name = display_name_for(contact)
    members = []
    if isinstance(contact.group_members, list):
        for item in contact.group_members:
            if not isinstance(item, dict):
                continue
            phone = str(item.get("phone_number") or "").strip()
            normalized_phone = normalize_phone(phone)
            provider_jid = mention_jid(
                str(item.get("provider_jid") or item.get("jid") or "")
            )
            if not provider_jid and len(normalize_phone(phone)) > 15:
                provider_jid = mention_jid(phone)
            if not provider_jid and not is_mentionable_phone(phone):
                continue
            member_name = str(item.get("name") or "").strip() or None
            members.append(
                {
                    "phone_number": normalized_phone,
                    "provider_jid": provider_jid,
                    "name": member_name,
                    "is_admin": bool(item.get("is_admin")),
                }
            )
    member_phones_without_names = {
        member["phone_number"]
        for member in members
        if is_mentionable_phone(member["phone_number"])
        and (
            not member["name"]
            or normalize_phone(str(member["name"])) == member["phone_number"]
        )
    }
    if member_phones_without_names:
        known_contacts = db.scalars(
            select(Contact).where(
                Contact.tenant_id == tenant_id,
                Contact.kind == ContactKind.DIRECT,
                Contact.phone_number.in_(member_phones_without_names),
            )
        )
        names_by_phone = {
            known.phone_number: known_name
            for known in known_contacts
            for known_name in [
                (
                    known.name
                    or known.push_name
                    or known.business_name
                    or known.verified_name
                )
            ]
            if known_name and normalize_phone(known_name) != known.phone_number
        }
        for member in members:
            known_name = names_by_phone.get(member["phone_number"])
            if known_name and (
                not member["name"]
                or normalize_phone(str(member["name"])) == member["phone_number"]
            ):
                member["name"] = known_name
    return ContactResponse(
        id=contact.id,
        kind=contact.kind,
        display_name=display_name,
        name=contact.name,
        push_name=contact.push_name,
        business_name=contact.business_name,
        verified_name=contact.verified_name,
        phone_number=contact.phone_number,
        about=contact.about,
        profile_picture_url=contact.profile_picture_url,
        is_on_whatsapp=contact.is_on_whatsapp,
        profile_synced_at=contact.profile_synced_at,
        profile_sync_error=contact.profile_sync_error,
        group_member_count=contact.group_member_count,
        group_members=members,
        first_interaction_at=first_interaction,
        last_interaction_at=last_interaction,
        conversation_count=conversation_count or 0,
        closed_conversation_count=closed_count or 0,
    )


@router.get("", response_model=ContactListResponse)
def list_contacts(
    q: str = Query(default="", max_length=80),
    limit: int = Query(default=30, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    context: AuthContext = Depends(get_auth_context),
    db: Session = Depends(get_db),
) -> ContactListResponse:
    query = q.strip()
    statement = visible_contact_statement(context, db)
    if query:
        pattern = f"%{query}%"
        statement = statement.where(
            or_(
                Contact.phone_number.ilike(pattern),
                Contact.name.ilike(pattern),
                Contact.push_name.ilike(pattern),
                Contact.business_name.ilike(pattern),
                Contact.verified_name.ilike(pattern),
            )
        )
    total = db.scalar(select(func.count()).select_from(statement.subquery())) or 0
    contacts = list(
        db.scalars(
            statement.order_by(
                func.lower(
                    func.coalesce(
                        Contact.name,
                        Contact.push_name,
                        Contact.business_name,
                        Contact.verified_name,
                        Contact.phone_number,
                    )
                ),
                Contact.phone_number,
            )
            .offset(offset)
            .limit(limit)
        )
    )
    allowed_channel_ids = accessible_channel_ids(db, context)
    return ContactListResponse(
        items=[
            contact_list_item(
                db,
                context.tenant_id,
                contact,
                allowed_channel_ids=allowed_channel_ids,
            )
            for contact in contacts
        ],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post("", response_model=ContactListItem, status_code=status.HTTP_201_CREATED)
def create_contact(
    payload: ContactCreateRequest,
    response: Response,
    context: AuthContext = Depends(get_auth_context),
    db: Session = Depends(get_db),
) -> ContactListItem:
    phone_number = validate_direct_phone(payload.phone_number)
    name = normalize_contact_name(payload.name)
    if name is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Informe o nome do contato.",
        )
    existing = db.scalar(
        select(Contact).where(
            Contact.tenant_id == context.tenant_id,
            Contact.phone_number == phone_number,
        )
    )
    if existing is not None:
        if existing.kind != ContactKind.DIRECT:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Este telefone já está associado a outro tipo de contato.",
            )
        if can_access_contact(db, context, existing):
            response.status_code = status.HTTP_200_OK
            return contact_list_item(
                db,
                context.tenant_id,
                existing,
                allowed_channel_ids=accessible_channel_ids(db, context),
            )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Este telefone já existe em outro canal.",
        )

    contact = Contact(
        tenant_id=context.tenant_id,
        kind=ContactKind.DIRECT,
        name=name,
        phone_number=phone_number,
    )
    db.add(contact)
    try:
        db.flush()
        db.add(
            AuditLog(
                tenant_id=context.tenant_id,
                user_id=context.user.id,
                action="contact.created",
                entity_type="contact",
                entity_id=contact.id,
                metadata_={"kind": ContactKind.DIRECT.value},
            )
        )
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        existing = db.scalar(
            select(Contact).where(
                Contact.tenant_id == context.tenant_id,
                Contact.phone_number == phone_number,
                Contact.kind == ContactKind.DIRECT,
            )
        )
        if existing is not None:
            response.status_code = status.HTTP_200_OK
            return contact_list_item(
                db,
                context.tenant_id,
                existing,
                allowed_channel_ids=accessible_channel_ids(db, context),
            )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Não foi possível criar este contato.",
        ) from exc
    db.refresh(contact)
    return contact_list_item(
        db,
        context.tenant_id,
        contact,
        allowed_channel_ids=accessible_channel_ids(db, context),
    )


@router.get("/search", response_model=list[ContactSearchResponse])
def search_contacts(
    q: str = Query(default="", max_length=80),
    limit: int = Query(default=20, ge=1, le=50),
    context: AuthContext = Depends(get_auth_context),
    db: Session = Depends(get_db),
) -> list[ContactSearchResponse]:
    query = q.strip()
    if len(query) < 2:
        return []

    pattern = f"%{query}%"
    statement = select(Contact).where(
        Contact.tenant_id == context.tenant_id,
        Contact.kind == ContactKind.DIRECT,
        or_(
            Contact.phone_number.ilike(pattern),
            Contact.name.ilike(pattern),
            Contact.push_name.ilike(pattern),
            Contact.business_name.ilike(pattern),
            Contact.verified_name.ilike(pattern),
        ),
    )
    allowed_channel_ids = accessible_channel_ids(db, context)
    if allowed_channel_ids is not None:
        statement = (
            statement.join(
                Conversation,
                (Conversation.contact_id == Contact.id)
                & (Conversation.tenant_id == context.tenant_id),
            )
            .where(Conversation.channel_id.in_(allowed_channel_ids))
            .distinct()
        )
    contacts = list(
        db.scalars(statement.order_by(Contact.name, Contact.phone_number).limit(limit))
    )
    return [
        ContactSearchResponse(
            id=contact.id,
            kind=contact.kind,
            display_name=display_name_for(contact),
            phone_number=contact.phone_number,
            profile_picture_url=contact.profile_picture_url,
        )
        for contact in contacts
    ]


@router.get("/{contact_id}", response_model=ContactResponse)
def get_contact(
    contact_id: UUID,
    context: AuthContext = Depends(get_auth_context),
    db: Session = Depends(get_db),
) -> ContactResponse:
    contact = get_tenant_contact(db, context.tenant_id, contact_id)
    allowed_channel_ids = accessible_channel_ids(db, context)
    ensure_contact_access(db, context, contact)
    return contact_response(
        db,
        context.tenant_id,
        contact,
        allowed_channel_ids=allowed_channel_ids,
    )


@router.patch("/{contact_id}", response_model=ContactResponse)
async def update_contact(
    contact_id: UUID,
    payload: ContactUpdateRequest,
    context: AuthContext = Depends(get_auth_context),
    db: Session = Depends(get_db),
) -> ContactResponse:
    contact = get_tenant_contact(db, context.tenant_id, contact_id)
    ensure_contact_access(db, context, contact)
    if contact.kind != ContactKind.DIRECT:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Somente contatos diretos podem ser editados.",
        )
    contact.name = normalize_contact_name(payload.name)
    db.add(
        AuditLog(
            tenant_id=context.tenant_id,
            user_id=context.user.id,
            action="contact.updated",
            entity_type="contact",
            entity_id=contact.id,
            metadata_={"fields": ["name"]},
        )
    )
    db.commit()
    await realtime_manager.broadcast(
        context.tenant_id,
        "contact.updated",
        {"id": str(contact.id)},
    )
    return contact_response(
        db,
        context.tenant_id,
        contact,
        allowed_channel_ids=accessible_channel_ids(db, context),
    )


@router.post(
    "/{contact_id}/conversations",
    response_model=ConversationResponse,
)
async def start_contact_conversation(
    contact_id: UUID,
    payload: ContactStartConversationRequest,
    response: Response,
    context: AuthContext = Depends(get_auth_context),
    db: Session = Depends(get_db),
) -> ConversationResponse:
    contact = get_tenant_contact(db, context.tenant_id, contact_id)
    ensure_contact_access(db, context, contact)
    if contact.kind != ContactKind.DIRECT:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Só é possível iniciar atendimento ativo com contato direto.",
        )
    ensure_channel_access(db, context, payload.channel_id)
    channel = db.scalar(
        select(WhatsAppChannel).where(
            WhatsAppChannel.id == payload.channel_id,
            WhatsAppChannel.tenant_id == context.tenant_id,
        )
    )
    if channel is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Canal não encontrado",
        )
    if channel.status != ChannelStatus.CONNECTED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="WhatsApp desconectado. Reconecte o canal antes de iniciar conversa.",
        )

    conversation = db.scalar(
        select(Conversation)
        .where(
            Conversation.tenant_id == context.tenant_id,
            Conversation.channel_id == channel.id,
            Conversation.contact_id == contact.id,
        )
        .with_for_update()
    )
    created = False
    reopened = False
    if conversation is None:
        conversation = Conversation(
            tenant_id=context.tenant_id,
            channel_id=channel.id,
            contact_id=contact.id,
            status=ConversationStatus.NEW,
        )
        db.add(conversation)
        db.flush()
        created = True
        response.status_code = status.HTTP_201_CREATED
    elif conversation.status == ConversationStatus.CLOSED:
        conversation.status = ConversationStatus.NEW
        conversation.assigned_user_id = None
        reopened = True
    if created or reopened:
        db.add(
            AuditLog(
                tenant_id=context.tenant_id,
                user_id=context.user.id,
                action="conversation.started_from_contact",
                entity_type="conversation",
                entity_id=conversation.id,
                metadata_={
                    "contact_id": str(contact.id),
                    "channel_id": str(channel.id),
                    "created": created,
                    "reopened": reopened,
                },
            )
        )
    db.commit()
    if created:
        await realtime_manager.broadcast(
            context.tenant_id,
            "conversation.created",
            {"id": str(conversation.id), "channel_id": str(channel.id)},
        )
    elif reopened:
        await realtime_manager.broadcast(
            context.tenant_id,
            "conversation.updated",
            {
                "id": str(conversation.id),
                "channel_id": str(channel.id),
                "status": conversation.status.value,
                "assigned_user_id": None,
            },
        )

    row = db.execute(
        conversation_query(
            context.tenant_id,
            context.user.id,
            allowed_channel_ids=accessible_channel_ids(db, context),
        ).where(Conversation.id == conversation.id)
    ).one()
    return conversation_response(row)


@router.post("/{contact_id}/refresh", response_model=ContactResponse)
async def refresh_contact(
    contact_id: UUID,
    payload: ContactRefreshRequest,
    context: AuthContext = Depends(get_auth_context),
    db: Session = Depends(get_db),
) -> ContactResponse:
    contact = get_tenant_contact(db, context.tenant_id, contact_id)
    ensure_channel_access(db, context, payload.channel_id)
    channel = db.scalar(
        select(WhatsAppChannel)
        .join(Conversation, Conversation.channel_id == WhatsAppChannel.id)
        .where(
            WhatsAppChannel.id == payload.channel_id,
            WhatsAppChannel.tenant_id == context.tenant_id,
            Conversation.tenant_id == context.tenant_id,
            Conversation.contact_id == contact.id,
        )
    )
    if channel is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Canal do contato não encontrado",
        )
    if channel.status != ChannelStatus.CONNECTED:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=OFFLINE_MESSAGE)

    try:
        await synchronize_contact_profile(
            db,
            channel=channel,
            contact=contact,
        )
    except ProviderConfigurationError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except NotImplementedError as exc:
        raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail=str(exc)) from exc

    db.commit()
    await realtime_manager.broadcast(
        context.tenant_id,
        "contact.updated",
        {"id": str(contact.id), "channel_id": str(channel.id)},
    )
    return contact_response(
        db,
        context.tenant_id,
        contact,
        allowed_channel_ids=accessible_channel_ids(db, context),
    )
