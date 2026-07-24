from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth.dependencies import AuthContext, get_auth_context
from app.channels.models import WhatsAppChannel
from app.common.enums import ChannelProvider, ChannelStatus, ConversationStatus
from app.contacts.models import Contact
from app.contacts.schemas import ContactRefreshRequest, ContactResponse
from app.conversations.models import Conversation
from app.database import get_db
from app.messages.models import Message
from app.providers.evolution_credentials import (
    ProviderConfigurationError,
    claim_evolution_credential,
)
from app.providers.factory import get_provider
from app.realtime.manager import realtime_manager

router = APIRouter(prefix="/contacts", tags=["contacts"])
OFFLINE_MESSAGE = "WhatsApp desconectado. Reconecte o canal antes de atualizar o contato."


def get_tenant_contact(db: Session, tenant_id: UUID, contact_id: UUID) -> Contact:
    contact = db.scalar(
        select(Contact).where(Contact.id == contact_id, Contact.tenant_id == tenant_id)
    )
    if contact is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Contato não encontrado")
    return contact


def contact_response(db: Session, tenant_id: UUID, contact: Contact) -> ContactResponse:
    conversation_count, closed_count = db.execute(
        select(
            func.count(Conversation.id),
            func.count(Conversation.id).filter(
                Conversation.status == ConversationStatus.CLOSED
            ),
        ).where(
            Conversation.tenant_id == tenant_id,
            Conversation.contact_id == contact.id,
        )
    ).one()
    first_interaction, last_interaction = db.execute(
        select(func.min(Message.created_at), func.max(Message.created_at))
        .select_from(Message)
        .join(Conversation, Conversation.id == Message.conversation_id)
        .where(
            Message.tenant_id == tenant_id,
            Conversation.tenant_id == tenant_id,
            Conversation.contact_id == contact.id,
        )
    ).one()
    display_name = (
        contact.name
        or contact.push_name
        or contact.business_name
        or contact.verified_name
        or contact.phone_number
    )
    return ContactResponse(
        id=contact.id,
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
        first_interaction_at=first_interaction,
        last_interaction_at=last_interaction,
        conversation_count=conversation_count or 0,
        closed_conversation_count=closed_count or 0,
    )


@router.get("/{contact_id}", response_model=ContactResponse)
def get_contact(
    contact_id: UUID,
    context: AuthContext = Depends(get_auth_context),
    db: Session = Depends(get_db),
) -> ContactResponse:
    contact = get_tenant_contact(db, context.tenant_id, contact_id)
    return contact_response(db, context.tenant_id, contact)


@router.post("/{contact_id}/refresh", response_model=ContactResponse)
async def refresh_contact(
    contact_id: UUID,
    payload: ContactRefreshRequest,
    context: AuthContext = Depends(get_auth_context),
    db: Session = Depends(get_db),
) -> ContactResponse:
    contact = get_tenant_contact(db, context.tenant_id, contact_id)
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
        if channel.provider == ChannelProvider.EVOLUTION_GO:
            claim_evolution_credential(db, channel)
        profile = await get_provider(channel.provider, channel).get_contact_profile(
            channel, contact.phone_number
        )
    except ProviderConfigurationError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except NotImplementedError as exc:
        raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail=str(exc)) from exc

    for field in (
        "push_name",
        "business_name",
        "verified_name",
        "about",
        "profile_picture_url",
        "is_on_whatsapp",
    ):
        value = getattr(profile, field)
        if value is not None:
            setattr(contact, field, value)
    if not contact.name and profile.push_name:
        contact.name = profile.push_name
    contact.profile_synced_at = datetime.now(UTC)
    contact.profile_sync_error = profile.error
    db.commit()
    await realtime_manager.broadcast(
        context.tenant_id,
        "contact.updated",
        {"id": str(contact.id), "channel_id": str(channel.id)},
    )
    return contact_response(db, context.tenant_id, contact)
