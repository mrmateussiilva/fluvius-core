from uuid import UUID

from pydantic import BaseModel, EmailStr, Field, model_validator


class LoginRequest(BaseModel):
    email: EmailStr
    password: str
    tenant_id: UUID | None = None
    tenant_slug: str | None = Field(
        default=None,
        min_length=2,
        max_length=100,
        pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$",
    )

    @model_validator(mode="after")
    def ensure_single_tenant_reference(self) -> "LoginRequest":
        if self.tenant_id is not None and self.tenant_slug is not None:
            raise ValueError("Informe apenas uma referência de empresa")
        return self


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


class TenantLoginResponse(BaseModel):
    name: str
    slug: str
