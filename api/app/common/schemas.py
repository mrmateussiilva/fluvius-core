from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class QuotedMessageResponse(BaseModel):
    id: UUID
    direction: str
    message_type: str
    body: str | None


class MessageAttachmentResponse(ORMModel):
    id: UUID
    file_name: str
    content_type: str
    size_bytes: int
    public_url: str


class MessageResponse(ORMModel):
    id: UUID
    conversation_id: UUID
    direction: str
    message_type: str
    status: str
    body: str | None
    reply_to_message_id: UUID | None
    reply_to_provider_message_id: str | None
    reply_to: QuotedMessageResponse | None = None
    attachments: list[MessageAttachmentResponse] = Field(default_factory=list)
    provider_message_id: str | None
    error: str | None
    attempt_count: int
    last_attempt_at: datetime | None
    sent_at: datetime | None
    delivered_at: datetime | None
    read_at: datetime | None
    edited_at: datetime | None
    edit_content_unavailable: bool
    created_at: datetime
