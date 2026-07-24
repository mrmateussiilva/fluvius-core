from uuid import UUID

from pydantic import BaseModel, Field


class MessageCreate(BaseModel):
    text: str = Field(min_length=1, max_length=10000)
    reply_to_message_id: UUID | None = None
