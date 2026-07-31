from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

SyncType = Literal["contacts", "messages", "all"]
SyncStatus = Literal["queued", "running", "completed", "partial", "failed"]


class SyncRunCreate(BaseModel):
    channel_id: UUID
    sync_type: SyncType = "all"
    recent_days: int = Field(default=7, ge=1, le=30)


class SyncRunResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    channel_id: UUID
    sync_type: SyncType
    status: SyncStatus
    recent_days: int
    total_items: int
    contact_items: int
    group_items: int
    message_event_items: int
    imported_group_items: int
    processed_items: int
    succeeded_items: int
    failed_items: int
    error: str | None
    started_at: datetime | None
    finished_at: datetime | None
    created_at: datetime
    updated_at: datetime
