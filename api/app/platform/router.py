from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth.dependencies import AuthContext, get_auth_context
from app.auth.schemas import TokenResponse
from app.auth.session import issue_session
from app.channels.models import WhatsAppChannel
from app.common.audit_models import AuditLog
from app.common.enums import ChannelStatus
from app.database import get_db
from app.platform.schemas import (
    PlatformTenantChannel,
    PlatformTenantCreate,
    PlatformTenantDetail,
    PlatformTenantMember,
    PlatformTenantSummary,
    PlatformTenantUpdate,
)
from app.realtime.manager import realtime_manager
from app.security import hash_password
from app.tenants.models import Tenant
from app.users.models import TenantUser, User


router = APIRouter(prefix="/platform", tags=["platform"])


def require_platform_admin(
    context: AuthContext = Depends(get_auth_context),
) -> AuthContext:
    if not context.user.is_platform_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Apenas administradores da plataforma podem acessar esta área",
        )
    return context


def get_platform_tenant(
    db: Session,
    tenant_id: UUID,
    *,
    for_update: bool = False,
) -> Tenant:
    query = select(Tenant).where(Tenant.id == tenant_id)
    if for_update:
        query = query.with_for_update()
    tenant = db.scalar(query)
    if tenant is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Empresa não encontrada",
        )
    return tenant


def tenant_summary(db: Session, tenant: Tenant) -> PlatformTenantSummary:
    user_count = db.scalar(
        select(func.count(TenantUser.id)).where(
            TenantUser.tenant_id == tenant.id,
        )
    )
    active_user_count = db.scalar(
        select(func.count(TenantUser.id))
        .join(
            User,
            (User.id == TenantUser.user_id)
            & (User.is_active.is_(True)),
        )
        .where(
            TenantUser.tenant_id == tenant.id,
            TenantUser.is_active.is_(True),
            User.is_active.is_(True),
        )
    )
    channel_count = db.scalar(
        select(func.count(WhatsAppChannel.id)).where(
            WhatsAppChannel.tenant_id == tenant.id,
        )
    )
    connected_channel_count = db.scalar(
        select(func.count(WhatsAppChannel.id)).where(
            WhatsAppChannel.tenant_id == tenant.id,
            WhatsAppChannel.status == ChannelStatus.CONNECTED,
        )
    )
    return PlatformTenantSummary(
        id=tenant.id,
        name=tenant.name,
        slug=tenant.slug,
        is_active=tenant.is_active,
        user_count=user_count or 0,
        active_user_count=active_user_count or 0,
        channel_count=channel_count or 0,
        connected_channel_count=connected_channel_count or 0,
        created_at=tenant.created_at,
    )


@router.get("/tenants", response_model=list[PlatformTenantSummary])
def list_platform_tenants(
    _: AuthContext = Depends(require_platform_admin),
    db: Session = Depends(get_db),
) -> list[PlatformTenantSummary]:
    tenants = list(db.scalars(select(Tenant).order_by(Tenant.name, Tenant.id)))
    return [tenant_summary(db, tenant) for tenant in tenants]


@router.get("/tenants/{tenant_id}", response_model=PlatformTenantDetail)
def get_platform_tenant_detail(
    tenant_id: UUID,
    _: AuthContext = Depends(require_platform_admin),
    db: Session = Depends(get_db),
) -> PlatformTenantDetail:
    tenant = get_platform_tenant(db, tenant_id)
    summary = tenant_summary(db, tenant)
    user_rows = db.execute(
        select(User, TenantUser)
        .join(
            TenantUser,
            (TenantUser.user_id == User.id)
            & (TenantUser.tenant_id == tenant.id),
        )
        .where(TenantUser.tenant_id == tenant.id)
        .order_by(TenantUser.is_active.desc(), User.name, User.id)
    ).all()
    channels = list(
        db.scalars(
            select(WhatsAppChannel)
            .where(WhatsAppChannel.tenant_id == tenant.id)
            .order_by(WhatsAppChannel.name, WhatsAppChannel.id)
        )
    )
    return PlatformTenantDetail(
        **summary.model_dump(),
        users=[
            PlatformTenantMember(
                id=user.id,
                name=user.name,
                email=user.email,
                role=membership.role,
                is_active=user.is_active and membership.is_active,
                is_platform_admin=user.is_platform_admin,
            )
            for user, membership in user_rows
        ],
        channels=[
            PlatformTenantChannel(
                id=channel.id,
                name=channel.name,
                phone_number=channel.phone_number,
                provider=channel.provider,
                status=channel.status,
            )
            for channel in channels
        ],
    )


@router.post(
    "/tenants",
    response_model=PlatformTenantSummary,
    status_code=status.HTTP_201_CREATED,
)
def create_platform_tenant(
    payload: PlatformTenantCreate,
    context: AuthContext = Depends(require_platform_admin),
    db: Session = Depends(get_db),
) -> PlatformTenantSummary:
    email = payload.admin_email.lower()
    if db.scalar(select(Tenant.id).where(Tenant.slug == payload.slug)) is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Este identificador de empresa já está em uso",
        )
    existing_admin = db.scalar(select(User).where(User.email == email))
    if existing_admin is not None:
        has_active_membership = db.scalar(
            select(TenantUser.id).where(
                TenantUser.user_id == existing_admin.id,
                TenantUser.is_active.is_(True),
            )
        )
        if existing_admin.is_platform_admin or has_active_membership is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "O e-mail já possui acesso ativo. Desative a associação "
                    "anterior ou use outro e-mail."
                ),
            )
    try:
        tenant = Tenant(name=payload.name, slug=payload.slug)
        db.add(tenant)
        db.flush()
        if existing_admin is None:
            admin = User(
                name=payload.admin_name,
                email=email,
                password_hash=hash_password(payload.admin_password),
            )
            db.add(admin)
            db.flush()
        else:
            admin = existing_admin
            admin.name = payload.admin_name
            admin.password_hash = hash_password(payload.admin_password)
            admin.is_active = True
        db.add(
            TenantUser(
                tenant_id=tenant.id,
                user_id=admin.id,
                role="admin",
            )
        )
        db.add(
            AuditLog(
                tenant_id=tenant.id,
                user_id=context.user.id,
                action="platform.tenant_created",
                entity_type="tenant",
                entity_id=tenant.id,
                metadata_={
                    "slug": tenant.slug,
                    "initial_admin_id": str(admin.id),
                    "reused_inactive_user": existing_admin is not None,
                },
            )
        )
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Empresa, identificador ou administrador já cadastrado",
        ) from exc
    return tenant_summary(db, tenant)


@router.patch("/tenants/{tenant_id}", response_model=PlatformTenantSummary)
async def update_platform_tenant(
    tenant_id: UUID,
    payload: PlatformTenantUpdate,
    context: AuthContext = Depends(require_platform_admin),
    db: Session = Depends(get_db),
) -> PlatformTenantSummary:
    tenant = get_platform_tenant(db, tenant_id, for_update=True)
    if tenant.id == context.tenant_id and not payload.is_active:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Troque de empresa antes de suspender a empresa atual",
        )
    previous = tenant.is_active
    tenant.is_active = payload.is_active
    db.add(
        AuditLog(
            tenant_id=tenant.id,
            user_id=context.user.id,
            action=(
                "platform.tenant_activated"
                if payload.is_active
                else "platform.tenant_suspended"
            ),
            entity_type="tenant",
            entity_id=tenant.id,
            metadata_={"previous_is_active": previous},
        )
    )
    db.commit()
    if not payload.is_active:
        await realtime_manager.disconnect_tenant(tenant.id)
    return tenant_summary(db, tenant)


@router.post("/tenants/{tenant_id}/access", response_model=TokenResponse)
def access_platform_tenant(
    tenant_id: UUID,
    response: Response,
    context: AuthContext = Depends(require_platform_admin),
    db: Session = Depends(get_db),
) -> TokenResponse:
    tenant = get_platform_tenant(db, tenant_id)
    if not tenant.is_active:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Ative a empresa antes de acessá-la",
        )
    membership = db.scalar(
        select(TenantUser)
        .where(
            TenantUser.tenant_id == tenant.id,
            TenantUser.user_id == context.user.id,
        )
        .with_for_update()
    )
    if membership is None:
        membership = TenantUser(
            tenant_id=tenant.id,
            user_id=context.user.id,
            role="admin",
        )
        db.add(membership)
    else:
        membership.role = "admin"
        membership.is_active = True
    db.flush()
    db.add(
        AuditLog(
            tenant_id=tenant.id,
            user_id=context.user.id,
            action="platform.support_access",
            entity_type="tenant",
            entity_id=tenant.id,
            metadata_={"origin_tenant_id": str(context.tenant_id)},
        )
    )
    db.commit()
    token = issue_session(response, context.user, membership)
    return TokenResponse(access_token=token)
