from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from app.common.enums import ContactKind


class ContactResponse(BaseModel):
    id: UUID
    kind: ContactKind = ContactKind.DIRECT
    display_name: str
    name: str | None
    push_name: str | None
    business_name: str | None
    verified_name: str | None
    phone_number: str
    about: str | None
    profile_picture_url: str | None
    is_on_whatsapp: bool | None
    profile_synced_at: datetime | None
    profile_sync_error: str | None
    first_interaction_at: datetime | None
    last_interaction_at: datetime | None
    conversation_count: int
    closed_conversation_count: int


class ContactRefreshRequest(BaseModel):
    channel_id: UUID
