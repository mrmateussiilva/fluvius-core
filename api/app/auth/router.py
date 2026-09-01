import logging

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.dependencies import AuthContext, get_auth_context
from app.auth.rate_limit import (
    clear_account_login_failures,
    ensure_login_allowed,
    record_login_failure,
)
from app.auth.schemas import (
    AvailableTenantResponse,
    CurrentUserResponse,
    CurrentUserUpdate,
    LoginRequest,
    TenantLoginResponse,
    TenantSwitchRequest,
    TokenResponse,
)
from app.auth.session import issue_session
from app.common.audit_models import AuditLog
from app.config import settings
from app.database import get_db
from app.security import hash_password, verify_password
from app.tenants.models import Tenant
from app.users.models import TenantUser, User

router = APIRouter(prefix="/auth", tags=["auth"])
logger = logging.getLogger(__name__)


def current_user_response(
    context: AuthContext,
    tenant: Tenant,
) -> CurrentUserResponse:
    return CurrentUserResponse(
        id=context.user.id,
        tenant_id=context.tenant_id,
        tenant_name=tenant.name,
        tenant_slug=tenant.slug,
        email=context.user.email,
        name=context.user.name,
        role=context.membership.role,
        is_platform_admin=context.user.is_platform_admin,
    )


@router.post("/login", response_model=TokenResponse)
def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
) -> TokenResponse:
    client_ip = request.client.host if request.client else "unknown"
    ensure_login_allowed(payload.email, client_ip)
    user = db.scalar(
        select(User).where(
            User.email == payload.email.lower(),
            User.is_active.is_(True),
        )
    )
    if user is None or not verify_password(payload.password, user.password_hash):
        record_login_failure(payload.email, client_ip)
        logger.warning("Falha de autenticação", extra={"client_ip": client_ip})
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="E-mail ou senha inválidos",
        )

    membership_query = (
        select(TenantUser)
        .join(
            Tenant,
            (Tenant.id == TenantUser.tenant_id) & (Tenant.is_active.is_(True)),
        )
        .where(
            TenantUser.user_id == user.id,
            TenantUser.is_active.is_(True),
            Tenant.is_active.is_(True),
        )
    )
    if payload.tenant_id:
        membership_query = membership_query.where(TenantUser.tenant_id == payload.tenant_id)
    if payload.tenant_slug:
        membership_query = membership_query.where(Tenant.slug == payload.tenant_slug)
    membership = db.scalar(membership_query.order_by(TenantUser.created_at))
    if membership is None:
        record_login_failure(payload.email, client_ip)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Usuário sem acesso ao tenant",
        )

    clear_account_login_failures(payload.email)
    token = issue_session(response, user, membership)
    logger.info(
        "Autenticação concluída",
        extra={"user_id": str(user.id), "tenant_id": str(membership.tenant_id)},
    )
    return TokenResponse(access_token=token)


@router.get(
    "/tenant-login/{tenant_slug}",
    response_model=TenantLoginResponse,
)
def tenant_login(
    tenant_slug: str,
    db: Session = Depends(get_db),
) -> TenantLoginResponse:
    tenant = db.scalar(
        select(Tenant).where(
            Tenant.slug == tenant_slug.lower(),
            Tenant.is_active.is_(True),
        )
    )
    if tenant is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Empresa não encontrada ou indisponível",
        )
    return TenantLoginResponse(name=tenant.name, slug=tenant.slug)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(response: Response) -> Response:
    response.delete_cookie(
        key=settings.auth_cookie_name,
        httponly=True,
        secure=settings.auth_cookie_secure,
        samesite="strict",
        path="/",
    )
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


@router.get("/me", response_model=CurrentUserResponse)
def me(
    context: AuthContext = Depends(get_auth_context),
    db: Session = Depends(get_db),
) -> CurrentUserResponse:
    tenant = db.scalar(
        select(Tenant).where(
            Tenant.id == context.tenant_id,
            Tenant.is_active.is_(True),
        )
    )
    if tenant is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Empresa inativa ou indisponível",
        )
    return current_user_response(context, tenant)


@router.patch("/me", response_model=CurrentUserResponse)
def update_me(
    payload: CurrentUserUpdate,
    context: AuthContext = Depends(get_auth_context),
    db: Session = Depends(get_db),
) -> CurrentUserResponse:
    tenant = db.scalar(
        select(Tenant).where(
            Tenant.id == context.tenant_id,
            Tenant.is_active.is_(True),
        )
    )
    if tenant is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Empresa inativa ou indisponível",
        )

    changes: list[str] = []
    if payload.name is not None and payload.name != context.user.name:
        context.user.name = payload.name
        changes.append("name")

    if payload.new_password is not None:
        current_password = payload.current_password
        if current_password is None or not verify_password(
            current_password.get_secret_value(),
            context.user.password_hash,
        ):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="A senha atual está incorreta",
            )
        context.user.password_hash = hash_password(payload.new_password.get_secret_value())
        changes.append("password")

    if not changes:
        return current_user_response(context, tenant)

    db.add(
        AuditLog(
            tenant_id=context.tenant_id,
            user_id=context.user.id,
            action="profile.updated",
            entity_type="user",
            entity_id=context.user.id,
            metadata_={"fields": changes},
        )
    )
    db.commit()
    db.refresh(context.user)
    return current_user_response(context, tenant)


@router.get("/tenants", response_model=list[AvailableTenantResponse])
def available_tenants(
    context: AuthContext = Depends(get_auth_context),
    db: Session = Depends(get_db),
) -> list[AvailableTenantResponse]:
    rows = db.execute(
        select(Tenant, TenantUser.role)
        .join(
            TenantUser,
            (TenantUser.tenant_id == Tenant.id) & (TenantUser.user_id == context.user.id),
        )
        .where(
            TenantUser.user_id == context.user.id,
            TenantUser.is_active.is_(True),
            Tenant.is_active.is_(True),
        )
        .order_by(Tenant.name, Tenant.id)
    ).all()
    return [
        AvailableTenantResponse(
            id=tenant.id,
            name=tenant.name,
            slug=tenant.slug,
            role=role,
        )
        for tenant, role in rows
    ]


@router.post("/switch-tenant", response_model=TokenResponse)
def switch_tenant(
    payload: TenantSwitchRequest,
    response: Response,
    context: AuthContext = Depends(get_auth_context),
    db: Session = Depends(get_db),
) -> TokenResponse:
    membership = db.scalar(
        select(TenantUser)
        .join(
            Tenant,
            (Tenant.id == TenantUser.tenant_id) & (Tenant.id == payload.tenant_id),
        )
        .where(
            TenantUser.tenant_id == payload.tenant_id,
            TenantUser.user_id == context.user.id,
            TenantUser.is_active.is_(True),
            Tenant.id == payload.tenant_id,
            Tenant.is_active.is_(True),
        )
    )
    if membership is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Você não possui acesso ativo a esta empresa",
        )
    token = issue_session(response, context.user, membership)
    return TokenResponse(access_token=token)
