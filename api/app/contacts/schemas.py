from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.common.enums import ContactKind


class GroupMemberResponse(BaseModel):
    phone_number: str
    provider_jid: str | None = None
    name: str | None = None
    is_admin: bool = False


class ContactResponse(BaseModel):
    id: UUID
    kind: ContactKind = ContactKind.DIRECT
    display_name: str
    name: str | None
    address_book_name: str | None
    push_name: str | None
    business_name: str | None
    verified_name: str | None
    phone_number: str
    about: str | None
    profile_picture_url: str | None
    is_on_whatsapp: bool | None
    profile_synced_at: datetime | None
    profile_sync_error: str | None
    group_member_count: int | None = None
    group_members: list[GroupMemberResponse] = Field(default_factory=list)
    first_interaction_at: datetime | None
    last_interaction_at: datetime | None
    conversation_count: int
    closed_conversation_count: int


class ContactSearchResponse(BaseModel):
    id: UUID
    kind: ContactKind = ContactKind.DIRECT
    display_name: str
    phone_number: str
    profile_picture_url: str | None = None


class ContactListItem(BaseModel):
    id: UUID
    kind: ContactKind = ContactKind.DIRECT
    display_name: str
    name: str | None
    phone_number: str
    profile_picture_url: str | None = None
    is_on_whatsapp: bool | None = None
    profile_synced_at: datetime | None = None
    conversation_count: int = 0
    last_interaction_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class ContactListResponse(BaseModel):
    items: list[ContactListItem]
    total: int
    limit: int
    offset: int


class ContactCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    phone_number: str = Field(min_length=8, max_length=32)


class ContactUpdateRequest(BaseModel):
    name: str | None = Field(default=None, max_length=160)


class ContactRefreshRequest(BaseModel):
    channel_id: UUID


class ContactStartConversationRequest(BaseModel):
    channel_id: UUID
