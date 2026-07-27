from dataclasses import dataclass
from uuid import UUID

import jwt
from fastapi import Cookie, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.security import decode_access_token
from app.tenants.models import Tenant
from app.users.models import TenantUser, User


bearer_scheme = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class AuthContext:
    user: User
    membership: TenantUser

    @property
    def tenant_id(self) -> UUID:
        return self.membership.tenant_id


def get_auth_context(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    session_token: str | None = Cookie(
        default=None,
        alias=settings.auth_cookie_name,
    ),
    db: Session = Depends(get_db),
) -> AuthContext:
    unauthorized = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Credenciais inválidas ou expiradas",
        headers={"WWW-Authenticate": "Bearer"},
    )
    token = credentials.credentials if credentials is not None else session_token
    if token is None:
        raise unauthorized
    try:
        payload = decode_access_token(token)
        user_id = UUID(payload["sub"])
        tenant_id = UUID(payload["tenant_id"])
    except (jwt.PyJWTError, KeyError, ValueError):
        raise unauthorized from None

    row = db.execute(
        select(User, TenantUser)
        .join(
            TenantUser,
            (TenantUser.user_id == User.id)
            & (TenantUser.tenant_id == tenant_id),
        )
        .join(
            Tenant,
            (Tenant.id == TenantUser.tenant_id)
            & (Tenant.id == tenant_id),
        )
        .where(
            User.id == user_id,
            User.is_active.is_(True),
            TenantUser.user_id == user_id,
            TenantUser.tenant_id == tenant_id,
            TenantUser.is_active.is_(True),
            Tenant.id == tenant_id,
            Tenant.is_active.is_(True),
        )
    ).one_or_none()
    if row is None:
        raise unauthorized
    user, membership = row
    return AuthContext(user=user, membership=membership)
