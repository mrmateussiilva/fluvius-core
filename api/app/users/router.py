from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth.dependencies import AuthContext, get_auth_context
from app.common.audit_models import AuditLog
from app.common.enums import ConversationStatus
from app.conversations.models import Conversation
from app.database import get_db
from app.realtime.manager import realtime_manager
from app.security import hash_password
from app.users.channel_access import user_channel_ids, validate_tenant_channel_ids
from app.users.models import TenantUser, TenantUserChannel, User
from app.users.schemas import (
    ActiveTenantUserResponse,
    TenantUserResponse,
    UserCreate,
    UserUpdate,
)


router = APIRouter(prefix="/users", tags=["users"])


def require_admin(
    context: AuthContext = Depends(get_auth_context),
) -> AuthContext:
    if context.membership.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Apenas administradores podem gerenciar usuários",
        )
    return context


def tenant_user_response(
    db: Session,
    user: User,
    membership: TenantUser,
) -> TenantUserResponse:
    return TenantUserResponse(
        id=user.id,
        name=user.name,
        email=user.email,
        role=membership.role,
        is_active=user.is_active and membership.is_active,
        is_platform_admin=user.is_platform_admin,
        channel_ids=user_channel_ids(
            db,
            membership.tenant_id,
            user.id,
            membership.role,
        ),
        created_at=membership.created_at,
    )


def all_tenant_channel_ids(db: Session, tenant_id: UUID) -> set[UUID]:
    from app.channels.models import WhatsAppChannel

    return set(
        db.scalars(
            select(WhatsAppChannel.id).where(
                WhatsAppChannel.tenant_id == tenant_id
            )
        )
    )


def replace_user_channels(
    db: Session,
    *,
    tenant_id: UUID,
    user_id: UUID,
    channel_ids: set[UUID],
) -> tuple[set[UUID], set[UUID]]:
    existing = set(
        db.scalars(
            select(TenantUserChannel.channel_id).where(
                TenantUserChannel.tenant_id == tenant_id,
                TenantUserChannel.user_id == user_id,
            )
        )
    )
    removed = existing - channel_ids
    added = channel_ids - existing
    if removed:
        db.execute(
            delete(TenantUserChannel).where(
                TenantUserChannel.tenant_id == tenant_id,
                TenantUserChannel.user_id == user_id,
                TenantUserChannel.channel_id.in_(removed),
            )
        )
    db.add_all(
        [
            TenantUserChannel(
                tenant_id=tenant_id,
                user_id=user_id,
                channel_id=channel_id,
            )
            for channel_id in added
        ]
    )
    return added, removed


def get_tenant_user(
    db: Session,
    tenant_id: UUID,
    user_id: UUID,
    *,
    for_update: bool = False,
) -> tuple[User, TenantUser]:
    query = (
        select(User, TenantUser)
        .join(
            TenantUser,
            (TenantUser.user_id == User.id) & (TenantUser.tenant_id == tenant_id),
        )
        .where(
            User.id == user_id,
            TenantUser.tenant_id == tenant_id,
            TenantUser.user_id == user_id,
        )
    )
    if for_update:
        query = query.with_for_update()
    result = db.execute(query).one_or_none()
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Usuário não encontrado",
        )
    return result[0], result[1]


@router.get("/active", response_model=list[ActiveTenantUserResponse])
def list_active_users(
    context: AuthContext = Depends(require_admin),
    db: Session = Depends(get_db),
) -> list[ActiveTenantUserResponse]:
    rows = db.execute(
        select(User, TenantUser)
        .join(
            TenantUser,
            (TenantUser.user_id == User.id)
            & (TenantUser.tenant_id == context.tenant_id),
        )
        .where(
            TenantUser.tenant_id == context.tenant_id,
            TenantUser.is_active.is_(True),
            User.is_active.is_(True),
        )
        .order_by(User.name, User.id)
    ).all()
    return [
        ActiveTenantUserResponse(
            id=user.id,
            name=user.name,
            role=membership.role,
            channel_ids=user_channel_ids(
                db,
                membership.tenant_id,
                user.id,
                membership.role,
            ),
        )
        for user, membership in rows
    ]


@router.get("", response_model=list[TenantUserResponse])
def list_users(
    context: AuthContext = Depends(require_admin),
    db: Session = Depends(get_db),
) -> list[TenantUserResponse]:
    rows = db.execute(
        select(User, TenantUser)
        .join(
            TenantUser,
            (TenantUser.user_id == User.id)
            & (TenantUser.tenant_id == context.tenant_id),
        )
        .where(TenantUser.tenant_id == context.tenant_id)
        .order_by(TenantUser.is_active.desc(), User.name, User.email)
    ).all()
    return [tenant_user_response(db, user, membership) for user, membership in rows]


@router.post(
    "",
    response_model=TenantUserResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_user(
    payload: UserCreate,
    context: AuthContext = Depends(require_admin),
    db: Session = Depends(get_db),
) -> TenantUserResponse:
    email = payload.email.lower()
    if db.scalar(select(User.id).where(User.email == email)) is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Este e-mail já está cadastrado",
        )

    try:
        user = User(
            email=email,
            name=payload.name,
            password_hash=hash_password(payload.password),
        )
        db.add(user)
        db.flush()
        membership = TenantUser(
            tenant_id=context.tenant_id,
            user_id=user.id,
            role=payload.role,
        )
        db.add(membership)
        db.flush()
        assigned_channel_ids: set[UUID] = set()
        if membership.role == "agent":
            assigned_channel_ids = validate_tenant_channel_ids(
                db,
                context.tenant_id,
                (
                    set(payload.channel_ids)
                    if payload.channel_ids is not None
                    else all_tenant_channel_ids(db, context.tenant_id)
                ),
            )
            replace_user_channels(
                db,
                tenant_id=context.tenant_id,
                user_id=user.id,
                channel_ids=assigned_channel_ids,
            )
        db.add(
            AuditLog(
                tenant_id=context.tenant_id,
                user_id=context.user.id,
                action="user.created",
                entity_type="user",
                entity_id=user.id,
                metadata_={
                    "role": payload.role,
                    "channel_ids": [
                        str(channel_id)
                        for channel_id in sorted(
                            assigned_channel_ids,
                            key=str,
                        )
                    ],
                },
            )
        )
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Este e-mail já está cadastrado",
        ) from exc
    return tenant_user_response(db, user, membership)


@router.patch("/{user_id}", response_model=TenantUserResponse)
async def update_user(
    user_id: UUID,
    payload: UserUpdate,
    context: AuthContext = Depends(require_admin),
    db: Session = Depends(get_db),
) -> TenantUserResponse:
    user, membership = get_tenant_user(
        db,
        context.tenant_id,
        user_id,
        for_update=True,
    )
    if user.is_platform_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="A conta da plataforma não pode ser alterada pela empresa",
        )
    if user.id == context.user.id and (
        payload.is_active is False
        or (payload.role is not None and payload.role != "admin")
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Você não pode remover o próprio acesso administrativo",
        )

    changes: list[str] = []
    previous_role = membership.role
    if payload.name is not None:
        user.name = payload.name
        changes.append("name")
    if payload.password is not None:
        user.password_hash = hash_password(payload.password)
        changes.append("password")
    if payload.role is not None:
        membership.role = payload.role
        changes.append("role")

    released_conversations: list[Conversation] = []
    existing_channel_ids = set(
        user_channel_ids(
            db,
            context.tenant_id,
            user.id,
            "agent",
        )
    )
    if membership.role == "admin":
        target_channel_ids: set[UUID] = set()
    elif payload.channel_ids is not None:
        target_channel_ids = validate_tenant_channel_ids(
            db,
            context.tenant_id,
            set(payload.channel_ids),
        )
    elif previous_role == "admin":
        target_channel_ids = all_tenant_channel_ids(db, context.tenant_id)
    else:
        target_channel_ids = existing_channel_ids
    _, removed_channel_ids = replace_user_channels(
        db,
        tenant_id=context.tenant_id,
        user_id=user.id,
        channel_ids=target_channel_ids,
    )
    if payload.channel_ids is not None or previous_role != membership.role:
        changes.append("channel_ids")

    if payload.is_active is not None:
        membership.is_active = payload.is_active
        changes.append("is_active")
    release_query = select(Conversation).where(
        Conversation.tenant_id == context.tenant_id,
        Conversation.assigned_user_id == user.id,
        Conversation.status == ConversationStatus.OPEN,
    )
    if membership.is_active and removed_channel_ids:
        release_query = release_query.where(
            Conversation.channel_id.in_(removed_channel_ids)
        )
    elif membership.is_active:
        release_query = None
    if release_query is not None:
        released_conversations = list(
            db.scalars(release_query.with_for_update())
        )
        for conversation in released_conversations:
            conversation.assigned_user_id = None
            conversation.status = ConversationStatus.NEW

    db.add(
        AuditLog(
            tenant_id=context.tenant_id,
            user_id=context.user.id,
            action="user.updated",
            entity_type="user",
            entity_id=user.id,
            metadata_={
                "fields": changes,
                "released_conversations": len(released_conversations),
                "channel_ids": [
                    str(channel_id)
                    for channel_id in sorted(
                        (
                            all_tenant_channel_ids(db, context.tenant_id)
                            if membership.role == "admin"
                            else target_channel_ids
                        ),
                        key=str,
                    )
                ],
            },
        )
    )
    db.commit()

    if "channel_ids" in changes or "role" in changes or "is_active" in changes:
        await realtime_manager.disconnect_user(
            context.tenant_id,
            user.id,
        )
    for conversation in released_conversations:
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
    return tenant_user_response(db, user, membership)
