from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.common.enums import ChannelProvider, ChannelStatus


class ChannelCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    phone_number: str | None = Field(default=None, max_length=32)
    provider: ChannelProvider = ChannelProvider.EVOLUTION_GO
    provider_config: dict = Field(default_factory=dict)


class ChannelResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    phone_number: str | None
    provider: ChannelProvider
    status: ChannelStatus
    provider_config: dict
