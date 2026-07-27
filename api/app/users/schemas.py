from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field, field_validator, model_validator


UserRole = Literal["admin", "agent"]


class UserCreate(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    role: UserRole = "agent"
    channel_ids: list[UUID] | None = None

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        normalized = " ".join(value.split())
        if len(normalized) < 2:
            raise ValueError("Nome deve ter ao menos 2 caracteres")
        return normalized


class UserUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=160)
    password: str | None = Field(default=None, min_length=8, max_length=128)
    role: UserRole | None = None
    is_active: bool | None = None
    channel_ids: list[UUID] | None = None

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
    def ensure_change(self) -> "UserUpdate":
        if not self.model_fields_set:
            raise ValueError("Informe ao menos uma alteração")
        return self


class TenantUserResponse(BaseModel):
    id: UUID
    name: str
    email: str
    role: UserRole
    is_active: bool
    is_platform_admin: bool
    channel_ids: list[UUID]
    created_at: datetime


class ActiveTenantUserResponse(BaseModel):
    id: UUID
    name: str
    role: UserRole
    channel_ids: list[UUID]
