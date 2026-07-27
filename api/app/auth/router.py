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
from app.auth.schemas import CurrentUserResponse, LoginRequest, TokenResponse
from app.config import settings
from app.database import get_db
from app.security import create_access_token, verify_password
from app.users.models import TenantUser, User


router = APIRouter(prefix="/auth", tags=["auth"])
logger = logging.getLogger(__name__)


@router.post("/login", response_model=TokenResponse)
def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
) -> TokenResponse:
    client_ip = request.client.host if request.client else "unknown"
    ensure_login_allowed(payload.email, client_ip)
    user = db.scalar(select(User).where(User.email == payload.email.lower(), User.is_active.is_(True)))
    if user is None or not verify_password(payload.password, user.password_hash):
        record_login_failure(payload.email, client_ip)
        logger.warning("Falha de autenticação", extra={"client_ip": client_ip})
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="E-mail ou senha inválidos")

    membership_query = select(TenantUser).where(
        TenantUser.user_id == user.id, TenantUser.is_active.is_(True)
    )
    if payload.tenant_id:
        membership_query = membership_query.where(TenantUser.tenant_id == payload.tenant_id)
    membership = db.scalar(membership_query.order_by(TenantUser.created_at))
    if membership is None:
        record_login_failure(payload.email, client_ip)
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Usuário sem acesso ao tenant")

    clear_account_login_failures(payload.email)
    token = create_access_token(str(user.id), str(membership.tenant_id), role=membership.role)
    response.set_cookie(
        key=settings.auth_cookie_name,
        value=token,
        max_age=settings.access_token_expire_minutes * 60,
        httponly=True,
        secure=settings.auth_cookie_secure,
        samesite="strict",
        path="/",
    )
    logger.info(
        "Autenticação concluída",
        extra={"user_id": str(user.id), "tenant_id": str(membership.tenant_id)},
    )
    return TokenResponse(access_token=token)


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
def me(context: AuthContext = Depends(get_auth_context)) -> CurrentUserResponse:
    return CurrentUserResponse(
        id=context.user.id,
        tenant_id=context.tenant_id,
        email=context.user.email,
        name=context.user.name,
        role=context.membership.role,
    )
