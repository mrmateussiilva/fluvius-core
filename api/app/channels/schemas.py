from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_serializer, model_validator

from app.common.enums import ChannelProvider, ChannelStatus


class ChannelCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    phone_number: str | None = Field(default=None, max_length=32)
    provider: ChannelProvider = ChannelProvider.EVOLUTION_GO
    provider_config: dict = Field(default_factory=dict)
    provisioning_key: UUID | None = None

    @model_validator(mode="after")
    def validate_provider_config(self) -> "ChannelCreate":
        if self.provider != ChannelProvider.EVOLUTION_GO:
            return self
        forbidden_keys = {
            "api_key",
            "apikey",
            "base_url",
            "global_api_key",
            "token",
        }
        if forbidden_keys.intersection(key.lower() for key in self.provider_config):
            raise ValueError("Credenciais do provider não podem ser enviadas pelo navegador")
        instance_name = self.provider_config.get("instance_name")
        if instance_name is None:
            self.provider_config = {}
            return self
        if not isinstance(instance_name, str) or not instance_name.strip():
            raise ValueError("A referência da instância Evolution é inválida")
        self.provider_config = {"instance_name": instance_name.strip()}
        return self


class ChannelResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    phone_number: str | None
    provider: ChannelProvider
    status: ChannelStatus
    provider_config: dict

    @field_serializer("provider_config")
    def serialize_provider_config(self, value: dict) -> dict[str, str]:
        instance_name = value.get("instance_name")
        return (
            {"instance_name": instance_name}
            if isinstance(instance_name, str) and instance_name
            else {}
        )
