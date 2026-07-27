from fastapi import Response

from app.config import settings
from app.security import create_access_token
from app.users.models import TenantUser, User


def issue_session(
    response: Response,
    user: User,
    membership: TenantUser,
) -> str:
    token = create_access_token(
        str(user.id),
        str(membership.tenant_id),
        role=membership.role,
    )
    response.set_cookie(
        key=settings.auth_cookie_name,
        value=token,
        max_age=settings.access_token_expire_minutes * 60,
        httponly=True,
        secure=settings.auth_cookie_secure,
        samesite="strict",
        path="/",
    )
    return token
