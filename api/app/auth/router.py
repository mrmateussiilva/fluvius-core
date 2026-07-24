from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.dependencies import AuthContext, get_auth_context
from app.auth.schemas import CurrentUserResponse, LoginRequest, TokenResponse
from app.database import get_db
from app.security import create_access_token, verify_password
from app.users.models import TenantUser, User


router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db)) -> TokenResponse:
    user = db.scalar(select(User).where(User.email == payload.email.lower(), User.is_active.is_(True)))
    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="E-mail ou senha inválidos")

    membership_query = select(TenantUser).where(
        TenantUser.user_id == user.id, TenantUser.is_active.is_(True)
    )
    if payload.tenant_id:
        membership_query = membership_query.where(TenantUser.tenant_id == payload.tenant_id)
    membership = db.scalar(membership_query.order_by(TenantUser.created_at))
    if membership is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Usuário sem acesso ao tenant")

    token = create_access_token(str(user.id), str(membership.tenant_id), role=membership.role)
    return TokenResponse(access_token=token)


@router.get("/me", response_model=CurrentUserResponse)
def me(context: AuthContext = Depends(get_auth_context)) -> CurrentUserResponse:
    return CurrentUserResponse(
        id=context.user.id,
        tenant_id=context.tenant_id,
        email=context.user.email,
        name=context.user.name,
        role=context.membership.role,
    )
