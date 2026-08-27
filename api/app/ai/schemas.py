import uuid
from typing import Literal

from pydantic import BaseModel, Field


class AiConfigRead(BaseModel):
    id: uuid.UUID
    channel_id: uuid.UUID
    is_enabled: bool = False
    provider: str = "openai"
    model_name: str = "gpt-4o-mini"
    has_api_key: bool = False
    system_prompt: str = ""
    bot_name: str = "IA Assistente"
    handoff_prompt: str = ""
    temperature: float = 0.3
    max_tokens: int = 500

    model_config = {"from_attributes": True}


class AiConfigUpdate(BaseModel):
    is_enabled: bool | None = None
    provider: str | None = None
    model_name: str | None = None
    api_key: str | None = None
    system_prompt: str | None = None
    bot_name: str | None = None
    handoff_prompt: str | None = None
    temperature: float | None = Field(None, ge=0.0, le=2.0)
    max_tokens: int | None = Field(None, ge=50, le=4000)


class SimulationMessage(BaseModel):
    role: Literal["user", "assistant", "system"]
    content: str


class AiSimulateRequest(BaseModel):
    messages: list[SimulationMessage]
    system_prompt: str | None = None
    handoff_prompt: str | None = None


class AiSimulateResponse(BaseModel):
    reply: str
    handoff_triggered: bool = False
    handoff_reason: str | None = None


class BotToggleRequest(BaseModel):
    is_bot_active: bool
    reason: str | None = None


class AiSummaryResponse(BaseModel):
    summary: str
    generated_at: str

