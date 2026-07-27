from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth.dependencies import AuthContext, get_auth_context
from app.common.audit_models import AuditLog
from app.common.enums import ConversationStatus
from app.conversations.models import Conversation
from app.database import get_db
from app.realtime.manager import realtime_manager
from app.security import hash_password
from app.users.models import TenantUser, User
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


def tenant_user_response(user: User, membership: TenantUser) -> TenantUserResponse:
    return TenantUserResponse(
        id=user.id,
        name=user.name,
        email=user.email,
        role=membership.role,
        is_active=user.is_active and membership.is_active,
        created_at=membership.created_at,
    )


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
    context: AuthContext = Depends(get_auth_context),
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
        ActiveTenantUserResponse(id=user.id, name=user.name, role=membership.role)
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
    return [tenant_user_response(user, membership) for user, membership in rows]


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
        db.add(
            AuditLog(
                tenant_id=context.tenant_id,
                user_id=context.user.id,
                action="user.created",
                entity_type="user",
                entity_id=user.id,
                metadata_={"role": payload.role},
            )
        )
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Este e-mail já está cadastrado",
        ) from exc
    return tenant_user_response(user, membership)


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
    if user.id == context.user.id and (
        payload.is_active is False
        or (payload.role is not None and payload.role != "admin")
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Você não pode remover o próprio acesso administrativo",
        )

    changes: list[str] = []
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
    if payload.is_active is not None:
        membership.is_active = payload.is_active
        changes.append("is_active")
        if not payload.is_active:
            released_conversations = list(
                db.scalars(
                    select(Conversation)
                    .where(
                        Conversation.tenant_id == context.tenant_id,
                        Conversation.assigned_user_id == user.id,
                        Conversation.status == ConversationStatus.OPEN,
                    )
                    .with_for_update()
                )
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
            },
        )
    )
    db.commit()

    for conversation in released_conversations:
        await realtime_manager.broadcast(
            context.tenant_id,
            "conversation.updated",
            {
                "id": str(conversation.id),
                "status": conversation.status.value,
                "assigned_user_id": None,
            },
        )
    return tenant_user_response(user, membership)
