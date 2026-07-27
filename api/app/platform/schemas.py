from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field, field_validator

from app.common.enums import ChannelProvider, ChannelStatus


class PlatformTenantCreate(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    slug: str = Field(min_length=2, max_length=100, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    admin_name: str = Field(min_length=2, max_length=160)
    admin_email: EmailStr
    admin_password: str = Field(min_length=12, max_length=128)

    @field_validator("name", "admin_name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        normalized = " ".join(value.split())
        if len(normalized) < 2:
            raise ValueError("Nome deve ter ao menos 2 caracteres")
        return normalized

    @field_validator("slug")
    @classmethod
    def normalize_slug(cls, value: str) -> str:
        return value.strip().lower()


class PlatformTenantUpdate(BaseModel):
    is_active: bool


class PlatformTenantSummary(BaseModel):
    id: UUID
    name: str
    slug: str
    is_active: bool
    user_count: int
    active_user_count: int
    channel_count: int
    connected_channel_count: int
    created_at: datetime


class PlatformTenantMember(BaseModel):
    id: UUID
    name: str
    email: str
    role: Literal["admin", "agent"]
    is_active: bool
    is_platform_admin: bool


class PlatformTenantChannel(BaseModel):
    id: UUID
    name: str
    phone_number: str | None
    provider: ChannelProvider
    status: ChannelStatus


class PlatformTenantDetail(PlatformTenantSummary):
    users: list[PlatformTenantMember]
    channels: list[PlatformTenantChannel]
