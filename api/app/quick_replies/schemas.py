from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class QuickReplyCreate(BaseModel):
    shortcut: str = Field(min_length=1, max_length=80)
    title: str = Field(min_length=1, max_length=160)
    content: str = Field(min_length=1, max_length=10000)


class QuickReplyResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    shortcut: str
    title: str
    content: str
