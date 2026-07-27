from uuid import UUID

from pydantic import BaseModel, EmailStr


class LoginRequest(BaseModel):
    email: EmailStr
    password: str
    tenant_id: UUID | None = None


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class CurrentUserResponse(BaseModel):
    id: UUID
    tenant_id: UUID
    tenant_name: str
    tenant_slug: str
    email: str
    name: str
    role: str
    is_platform_admin: bool


class TenantSwitchRequest(BaseModel):
    tenant_id: UUID


class AvailableTenantResponse(BaseModel):
    id: UUID
    name: str
    slug: str
    role: str
