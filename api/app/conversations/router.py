from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.auth.dependencies import AuthContext, get_auth_context
from app.channels.models import WhatsAppChannel
from app.common.enums import ConversationStatus, MessageDirection
from app.contacts.models import Contact
from app.conversations.models import Conversation, ConversationRead
from app.conversations.schemas import AssignRequest, ConversationResponse
from app.database import get_db
from app.messages.models import Message
from app.realtime.manager import realtime_manager
from app.users.models import TenantUser


router = APIRouter(prefix="/conversations", tags=["conversations"])
ASSIGNMENT_REQUIRED = "Assuma o atendimento antes de continuar"
ASSIGNED_TO_ANOTHER_AGENT = "Atendimento já assumido por outro agente"


def conversation_query(tenant_id: UUID, user_id: UUID):
    def last_message_value(column):
        return (
            select(column)
            .where(
                Message.tenant_id == tenant_id,
                Message.conversation_id == Conversation.id,
            )
            .order_by(Message.created_at.desc())
            .limit(1)
            .correlate(Conversation)
            .scalar_subquery()
        )

    last_read_at = (
        select(ConversationRead.last_read_at)
        .where(
            ConversationRead.tenant_id == tenant_id,
            ConversationRead.conversation_id == Conversation.id,
            ConversationRead.user_id == user_id,
        )
        .correlate(Conversation)
        .scalar_subquery()
    )
    unread_count = (
        select(func.count(Message.id))
        .where(
            Message.tenant_id == tenant_id,
            Message.conversation_id == Conversation.id,
            Message.direction == MessageDirection.INCOMING,
            or_(last_read_at.is_(None), Message.created_at > last_read_at),
        )
        .correlate(Conversation)
        .scalar_subquery()
    )
    return (
        select(
            Conversation,
            Contact,
            WhatsAppChannel,
            last_message_value(Message.body).label("last_message_body"),
            last_message_value(Message.message_type).label("last_message_type"),
            last_message_value(Message.direction).label("last_message_direction"),
            unread_count.label("unread_count"),
        )
        .join(
            Contact,
            (Contact.id == Conversation.contact_id) & (Contact.tenant_id == tenant_id),
        )
        .join(
            WhatsAppChannel,
            (WhatsAppChannel.id == Conversation.channel_id)
            & (WhatsAppChannel.tenant_id == tenant_id),
        )
        .where(Conversation.tenant_id == tenant_id)
    )


def as_response(row) -> ConversationResponse:
    (
        conversation,
        contact,
        channel,
        last_message_body,
        last_message_type,
        last_message_direction,
        unread_count,
    ) = row
    return ConversationResponse(
        id=conversation.id,
        status=conversation.status,
        assigned_user_id=conversation.assigned_user_id,
        contact_id=contact.id,
        contact_name=(
            contact.name
            or contact.push_name
            or contact.business_name
            or contact.verified_name
        ),
        contact_phone=contact.phone_number,
        channel_id=channel.id,
        channel_status=channel.status,
        last_message_at=conversation.last_message_at,
        last_message_body=last_message_body,
        last_message_type=last_message_type,
        last_message_direction=last_message_direction,
        unread_count=unread_count or 0,
    )


def get_tenant_conversation(db: Session, tenant_id: UUID, conversation_id: UUID) -> Conversation:
    conversation = db.scalar(
        select(Conversation).where(
            Conversation.id == conversation_id, Conversation.tenant_id == tenant_id
        )
    )
    if conversation is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversa não encontrada",
        )
    return conversation


def get_tenant_conversation_for_update(
    db: Session, tenant_id: UUID, conversation_id: UUID
) -> Conversation:
    conversation = db.scalar(
        select(Conversation)
        .where(
            Conversation.id == conversation_id,
            Conversation.tenant_id == tenant_id,
        )
        .with_for_update()
    )
    if conversation is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversa não encontrada",
        )
    return conversation


def ensure_conversation_assignee(conversation: Conversation, user_id: UUID) -> None:
    if (
        conversation.status != ConversationStatus.OPEN
        or conversation.assigned_user_id is None
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=ASSIGNMENT_REQUIRED,
        )
    if conversation.assigned_user_id != user_id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=ASSIGNED_TO_ANOTHER_AGENT,
        )


@router.get("", response_model=list[ConversationResponse])
def list_conversations(
    context: AuthContext = Depends(get_auth_context), db: Session = Depends(get_db)
) -> list[ConversationResponse]:
    rows = db.execute(
        conversation_query(context.tenant_id, context.user.id).order_by(
            Conversation.last_message_at.desc().nullslast(), Conversation.created_at.desc()
        )
    ).all()
    return [as_response(row) for row in rows]


@router.get("/{conversation_id}", response_model=ConversationResponse)
def get_conversation(
    conversation_id: UUID,
    context: AuthContext = Depends(get_auth_context),
    db: Session = Depends(get_db),
) -> ConversationResponse:
    row = db.execute(
        conversation_query(context.tenant_id, context.user.id).where(
            Conversation.id == conversation_id
        )
    ).one_or_none()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversa não encontrada",
        )
    return as_response(row)


@router.post("/{conversation_id}/read", status_code=status.HTTP_204_NO_CONTENT)
def mark_conversation_read(
    conversation_id: UUID,
    context: AuthContext = Depends(get_auth_context),
    db: Session = Depends(get_db),
) -> Response:
    get_tenant_conversation(db, context.tenant_id, conversation_id)
    marker = db.scalar(
        select(ConversationRead).where(
            ConversationRead.tenant_id == context.tenant_id,
            ConversationRead.conversation_id == conversation_id,
            ConversationRead.user_id == context.user.id,
        )
    )
    now = datetime.now(UTC)
    if marker is None:
        db.add(
            ConversationRead(
                tenant_id=context.tenant_id,
                conversation_id=conversation_id,
                user_id=context.user.id,
                last_read_at=now,
            )
        )
    else:
        marker.last_read_at = now
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{conversation_id}/assign", response_model=ConversationResponse)
async def assign_conversation(
    conversation_id: UUID,
    payload: AssignRequest,
    context: AuthContext = Depends(get_auth_context),
    db: Session = Depends(get_db),
) -> ConversationResponse:
    conversation = get_tenant_conversation_for_update(
        db, context.tenant_id, conversation_id
    )
    assignee_id = payload.user_id or context.user.id
    membership = db.scalar(
        select(TenantUser).where(
            TenantUser.tenant_id == context.tenant_id,
            TenantUser.user_id == assignee_id,
            TenantUser.is_active.is_(True),
        )
    )
    if membership is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Atendente fora do tenant",
        )
    if assignee_id != context.user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Transferência de atendimento não disponível no MVP",
        )
    if (
        conversation.status == ConversationStatus.OPEN
        and conversation.assigned_user_id is not None
        and conversation.assigned_user_id != assignee_id
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=ASSIGNED_TO_ANOTHER_AGENT,
        )
    conversation.assigned_user_id = assignee_id
    conversation.status = ConversationStatus.OPEN
    db.commit()
    await realtime_manager.broadcast(
        context.tenant_id,
        "conversation.updated",
        {
            "id": str(conversation.id),
            "status": conversation.status.value,
            "assigned_user_id": str(conversation.assigned_user_id),
        },
    )
    return get_conversation(conversation_id, context, db)


@router.post("/{conversation_id}/close", response_model=ConversationResponse)
async def close_conversation(
    conversation_id: UUID,
    context: AuthContext = Depends(get_auth_context),
    db: Session = Depends(get_db),
) -> ConversationResponse:
    conversation = get_tenant_conversation_for_update(
        db, context.tenant_id, conversation_id
    )
    ensure_conversation_assignee(conversation, context.user.id)
    conversation.status = ConversationStatus.CLOSED
    db.commit()
    await realtime_manager.broadcast(
        context.tenant_id,
        "conversation.updated",
        {
            "id": str(conversation.id),
            "status": conversation.status.value,
            "assigned_user_id": str(conversation.assigned_user_id),
        },
    )
    return get_conversation(conversation_id, context, db)
