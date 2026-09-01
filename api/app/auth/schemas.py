from uuid import UUID

from pydantic import BaseModel, EmailStr, Field, SecretStr, field_validator, model_validator


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


class CurrentUserUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=160)
    current_password: SecretStr | None = None
    new_password: SecretStr | None = Field(default=None, min_length=8, max_length=128)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = " ".join(value.split())
        if len(normalized) < 2:
            raise ValueError("Nome deve ter ao menos 2 caracteres")
        return normalized

    @model_validator(mode="after")
    def validate_change(self) -> "CurrentUserUpdate":
        if self.name is None and self.new_password is None:
            raise ValueError("Informe ao menos uma alteração")
        if self.new_password is not None and self.current_password is None:
            raise ValueError("Informe a senha atual para definir uma nova senha")
        return self


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
