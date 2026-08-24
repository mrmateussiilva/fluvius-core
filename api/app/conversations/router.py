from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.auth.dependencies import AuthContext, get_auth_context
from app.channels.models import WhatsAppChannel
from app.common.audit_models import AuditLog
from app.common.enums import ContactKind, ConversationStatus, MessageDirection
from app.contacts.models import Contact
from app.contacts.naming import contact_display_name
from app.conversations.models import Conversation, ConversationRead
from app.conversations.schemas import (
    AssignRequest,
    ConversationReadRequest,
    ConversationResponse,
)
from app.database import get_db
from app.messages.models import Message
from app.realtime.manager import realtime_manager
from app.users.channel_access import accessible_channel_ids, ensure_channel_access
from app.users.models import TenantUser, TenantUserChannel, User

router = APIRouter(prefix="/conversations", tags=["conversations"])
ASSIGNMENT_REQUIRED = "Assuma o atendimento antes de continuar"
ASSIGNED_TO_ANOTHER_AGENT = "Atendimento já assumido por outro agente"
ADMIN_TRANSFER_REQUIRED = "Apenas administradores podem transferir atendimentos"
ADMIN_RELEASE_REQUIRED = "Apenas administradores podem liberar atendimentos"


def conversation_query(
    tenant_id: UUID,
    user_id: UUID,
    *,
    allowed_channel_ids: set[UUID] | None = None,
    channel_id: UUID | None = None,
    contact_kind: ContactKind | None = None,
):
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
    query = (
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
    if allowed_channel_ids is not None:
        query = query.where(Conversation.channel_id.in_(allowed_channel_ids))
    if channel_id is not None:
        query = query.where(Conversation.channel_id == channel_id)
    if contact_kind is not None:
        query = query.where(Contact.kind == contact_kind)
    return query


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
        contact_kind=contact.kind,
        contact_name=contact_display_name(contact),
        contact_phone=contact.phone_number,
        channel_id=channel.id,
        channel_name=channel.name,
        channel_status=channel.status,
        last_message_at=conversation.last_message_at,
        last_message_body=last_message_body,
        last_message_type=last_message_type,
        last_message_direction=last_message_direction,
        unread_count=unread_count or 0,
        is_bot_active=conversation.is_bot_active,
        bot_handoff_at=conversation.bot_handoff_at,
        bot_handoff_reason=conversation.bot_handoff_reason,
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


def get_accessible_conversation(
    db: Session,
    context: AuthContext,
    conversation_id: UUID,
    *,
    for_update: bool = False,
) -> Conversation:
    conversation = (
        get_tenant_conversation_for_update(
            db,
            context.tenant_id,
            conversation_id,
        )
        if for_update
        else get_tenant_conversation(
            db,
            context.tenant_id,
            conversation_id,
        )
    )
    ensure_channel_access(db, context, conversation.channel_id)
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
    channel_id: UUID | None = Query(default=None),
    kind: ContactKind | None = Query(default=None),
    context: AuthContext = Depends(get_auth_context),
    db: Session = Depends(get_db),
) -> list[ConversationResponse]:
    if channel_id is not None:
        channel = db.scalar(
            select(WhatsAppChannel).where(
                WhatsAppChannel.id == channel_id,
                WhatsAppChannel.tenant_id == context.tenant_id,
            )
        )
        if channel is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Canal não encontrado",
            )
        ensure_channel_access(db, context, channel_id)
    rows = db.execute(
        conversation_query(
            context.tenant_id,
            context.user.id,
            allowed_channel_ids=accessible_channel_ids(db, context),
            channel_id=channel_id,
            contact_kind=kind,
        ).order_by(
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
        conversation_query(
            context.tenant_id,
            context.user.id,
            allowed_channel_ids=accessible_channel_ids(db, context),
        ).where(
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
    payload: ConversationReadRequest | None = None,
    context: AuthContext = Depends(get_auth_context),
    db: Session = Depends(get_db),
) -> Response:
    get_accessible_conversation(db, context, conversation_id)
    read_through = datetime.now(UTC)
    if payload and payload.through_message_id:
        visible_message = db.scalar(
            select(Message).where(
                Message.id == payload.through_message_id,
                Message.tenant_id == context.tenant_id,
                Message.conversation_id == conversation_id,
                Message.direction == MessageDirection.INCOMING,
            )
        )
        if visible_message is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Mensagem visível não encontrada",
            )
        read_through = visible_message.created_at
    marker = db.scalar(
        select(ConversationRead).where(
            ConversationRead.tenant_id == context.tenant_id,
            ConversationRead.conversation_id == conversation_id,
            ConversationRead.user_id == context.user.id,
        )
    )
    if marker is None:
        db.add(
            ConversationRead(
                tenant_id=context.tenant_id,
                conversation_id=conversation_id,
                user_id=context.user.id,
                last_read_at=read_through,
            )
        )
    elif marker.last_read_at < read_through:
        marker.last_read_at = read_through
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{conversation_id}/assign", response_model=ConversationResponse)
async def assign_conversation(
    conversation_id: UUID,
    payload: AssignRequest,
    context: AuthContext = Depends(get_auth_context),
    db: Session = Depends(get_db),
) -> ConversationResponse:
    conversation = get_accessible_conversation(
        db,
        context,
        conversation_id,
        for_update=True,
    )
    assignee_id = payload.user_id or context.user.id
    is_admin = context.membership.role == "admin"
    if assignee_id != context.user.id and not is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=ADMIN_TRANSFER_REQUIRED,
        )
    membership = db.scalar(
        select(TenantUser)
        .join(User, User.id == TenantUser.user_id)
        .where(
            TenantUser.tenant_id == context.tenant_id,
            TenantUser.user_id == assignee_id,
            TenantUser.is_active.is_(True),
            User.is_active.is_(True),
        )
    )
    if membership is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Atendente fora do tenant",
        )
    if membership.role != "admin":
        channel_membership = db.scalar(
            select(TenantUserChannel.id).where(
                TenantUserChannel.tenant_id == context.tenant_id,
                TenantUserChannel.user_id == assignee_id,
                TenantUserChannel.channel_id == conversation.channel_id,
            )
        )
        if channel_membership is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Atendente não possui acesso a este canal",
            )
    if (
        conversation.status == ConversationStatus.OPEN
        and conversation.assigned_user_id is not None
        and conversation.assigned_user_id != assignee_id
        and not is_admin
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=ASSIGNED_TO_ANOTHER_AGENT,
        )
    previous_assignee_id = conversation.assigned_user_id
    previous_status = conversation.status
    conversation.assigned_user_id = assignee_id
    conversation.status = ConversationStatus.OPEN
    changed = (
        previous_assignee_id != conversation.assigned_user_id
        or previous_status != conversation.status
    )
    if changed:
        assignment_mode = (
            "transfer"
            if assignee_id != context.user.id
            else "takeover"
            if previous_assignee_id is not None
            and previous_assignee_id != context.user.id
            else "claim"
        )
        db.add(
            AuditLog(
                tenant_id=context.tenant_id,
                user_id=context.user.id,
                action="conversation.assigned",
                entity_type="conversation",
                entity_id=conversation.id,
                metadata_={
                    "mode": assignment_mode,
                    "previous_assigned_user_id": (
                        str(previous_assignee_id) if previous_assignee_id else None
                    ),
                    "assigned_user_id": str(assignee_id),
                    "previous_status": previous_status.value,
                    "status": conversation.status.value,
                },
            )
        )
    db.commit()
    if changed:
        await realtime_manager.broadcast(
            context.tenant_id,
            "conversation.updated",
            {
                "id": str(conversation.id),
                "channel_id": str(conversation.channel_id),
                "status": conversation.status.value,
                "assigned_user_id": str(conversation.assigned_user_id),
            },
        )
    return get_conversation(conversation_id, context, db)


@router.post("/{conversation_id}/release", response_model=ConversationResponse)
async def release_conversation(
    conversation_id: UUID,
    context: AuthContext = Depends(get_auth_context),
    db: Session = Depends(get_db),
) -> ConversationResponse:
    conversation = get_accessible_conversation(
        db,
        context,
        conversation_id,
        for_update=True,
    )
    if context.membership.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=ADMIN_RELEASE_REQUIRED,
        )
    if conversation.status != ConversationStatus.OPEN:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Somente atendimentos abertos podem voltar para a fila",
        )

    previous_assignee_id = conversation.assigned_user_id
    previous_status = conversation.status
    conversation.assigned_user_id = None
    conversation.status = ConversationStatus.NEW
    db.add(
        AuditLog(
            tenant_id=context.tenant_id,
            user_id=context.user.id,
            action="conversation.released",
            entity_type="conversation",
            entity_id=conversation.id,
            metadata_={
                "previous_assigned_user_id": (
                    str(previous_assignee_id) if previous_assignee_id else None
                ),
                "assigned_user_id": None,
                "previous_status": previous_status.value,
                "status": conversation.status.value,
            },
        )
    )
    db.commit()
    await realtime_manager.broadcast(
        context.tenant_id,
        "conversation.updated",
        {
            "id": str(conversation.id),
            "channel_id": str(conversation.channel_id),
            "status": conversation.status.value,
            "assigned_user_id": None,
        },
    )
    return get_conversation(conversation_id, context, db)


@router.post("/{conversation_id}/close", response_model=ConversationResponse)
async def close_conversation(
    conversation_id: UUID,
    context: AuthContext = Depends(get_auth_context),
    db: Session = Depends(get_db),
) -> ConversationResponse:
    conversation = get_accessible_conversation(
        db,
        context,
        conversation_id,
        for_update=True,
    )
    ensure_conversation_assignee(conversation, context.user.id)
    conversation.status = ConversationStatus.CLOSED
    db.commit()
    await realtime_manager.broadcast(
        context.tenant_id,
        "conversation.updated",
        {
            "id": str(conversation.id),
            "channel_id": str(conversation.channel_id),
            "status": conversation.status.value,
            "assigned_user_id": str(conversation.assigned_user_id),
        },
    )
    return get_conversation(conversation_id, context, db)
