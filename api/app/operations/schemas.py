from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel

from app.common.enums import ChannelStatus


OperationalStatus = Literal["healthy", "attention", "critical"]


class OperationalChannelHealth(BaseModel):
    id: UUID
    name: str
    phone_number: str | None
    status: ChannelStatus
    last_event_at: datetime | None


class OperationalHealthResponse(BaseModel):
    status: OperationalStatus
    generated_at: datetime
    redis_available: bool
    delivery_worker_online: bool
    maintenance_worker_online: bool
    pending_deliveries: int
    delayed_deliveries: int
    failed_deliveries_24h: int
    oldest_pending_at: datetime | None
    connected_channels: int
    total_channels: int
    issues: list[str]
    channels: list[OperationalChannelHealth]
