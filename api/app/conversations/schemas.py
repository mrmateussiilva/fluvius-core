from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from app.common.enums import (
    ChannelStatus,
    ConversationStatus,
    MessageDirection,
    MessageType,
)


class ConversationResponse(BaseModel):
    id: UUID
    status: ConversationStatus
    assigned_user_id: UUID | None
    contact_id: UUID
    contact_name: str | None
    contact_phone: str
    channel_id: UUID
    channel_name: str
    channel_status: ChannelStatus
    last_message_at: datetime | None
    last_message_body: str | None = None
    last_message_type: MessageType | None = None
    last_message_direction: MessageDirection | None = None
    unread_count: int = 0


class AssignRequest(BaseModel):
    user_id: UUID | None = None


class ConversationReadRequest(BaseModel):
    through_message_id: UUID | None = None
