from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class MessageCreate(BaseModel):
    text: str = Field(min_length=1, max_length=10000)
    reply_to_message_id: UUID | None = None
    mentioned_phones: list[str] = Field(default_factory=list, max_length=50)
    mentioned_jids: list[str] = Field(default_factory=list, max_length=50)
    referenced_contact_ids: list[UUID] = Field(default_factory=list, max_length=50)
    client_message_id: UUID = Field(default_factory=uuid4)


class ContactMessageCreate(BaseModel):
    contact_id: UUID | None = None
    display_name: str | None = Field(default=None, max_length=160)
    phone_number: str | None = Field(default=None, max_length=32)
    organization: str | None = Field(default=None, max_length=160)
    reply_to_message_id: UUID | None = None
    client_message_id: UUID = Field(default_factory=uuid4)
