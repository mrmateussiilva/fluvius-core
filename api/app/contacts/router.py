from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.auth.dependencies import AuthContext, get_auth_context
from app.channels.models import WhatsAppChannel
from app.common.enums import ChannelStatus, ContactKind, ConversationStatus
from app.contacts.models import Contact
from app.contacts.schemas import (
    ContactRefreshRequest,
    ContactResponse,
    ContactSearchResponse,
)
from app.contacts.service import synchronize_contact_profile
from app.conversations.models import Conversation
from app.database import get_db
from app.messages.models import Message
from app.providers.evolution_credentials import ProviderConfigurationError
from app.realtime.manager import realtime_manager
from app.users.channel_access import accessible_channel_ids, ensure_channel_access

router = APIRouter(prefix="/contacts", tags=["contacts"])
OFFLINE_MESSAGE = "WhatsApp desconectado. Reconecte o canal antes de atualizar o contato."


def get_tenant_contact(db: Session, tenant_id: UUID, contact_id: UUID) -> Contact:
    contact = db.scalar(
        select(Contact).where(Contact.id == contact_id, Contact.tenant_id == tenant_id)
    )
    if contact is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Contato não encontrado")
    return contact


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
    display_name = (
        contact.name
        or contact.push_name
        or contact.business_name
        or contact.verified_name
        or contact.phone_number
    )
    members = []
    if isinstance(contact.group_members, list):
        for item in contact.group_members:
            if not isinstance(item, dict):
                continue
            phone = str(item.get("phone_number") or "").strip()
            if not phone:
                continue
            members.append(
                {
                    "phone_number": phone,
                    "name": item.get("name"),
                    "is_admin": bool(item.get("is_admin")),
                }
            )
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
            display_name=(
                contact.name
                or contact.push_name
                or contact.business_name
                or contact.verified_name
                or contact.phone_number
            ),
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
    if allowed_channel_ids is not None:
        accessible_conversation = db.scalar(
            select(Conversation.id).where(
                Conversation.tenant_id == context.tenant_id,
                Conversation.contact_id == contact.id,
                Conversation.channel_id.in_(allowed_channel_ids),
            )
        )
        if accessible_conversation is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Contato não encontrado",
            )
    return contact_response(
        db,
        context.tenant_id,
        contact,
        allowed_channel_ids=allowed_channel_ids,
    )


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
