from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.common.enums import ChannelStatus

OperationalStatus = Literal["healthy", "attention", "critical"]


class OperationalChannelHealth(BaseModel):
    id: UUID
    name: str
    phone_number: str | None
    status: ChannelStatus
    last_event_at: datetime | None
    pending_events: int = 0
    failed_events: int = 0
    webhook_stale: bool = False


class WebhookReconcileRuntimeResponse(BaseModel):
    active: bool
    heartbeat_at: datetime | None = None
    last_started_at: datetime | None = None
    last_finished_at: datetime | None = None
    last_error_at: datetime | None = None
    last_error: str | None = None
    last_scanned_channels: int = 0
    last_checked_events: int = 0
    last_resolved_events: int = 0


class HistoryReconcileRuntimeResponse(BaseModel):
    active: bool
    heartbeat_at: datetime | None = None
    last_started_at: datetime | None = None
    last_finished_at: datetime | None = None
    last_error_at: datetime | None = None
    last_error: str | None = None
    last_scanned_channels: int = 0
    last_checked_threads: int = 0
    last_requested_threads: int = 0
    last_failed_threads: int = 0


class OperationalHealthResponse(BaseModel):
    status: OperationalStatus
    generated_at: datetime
    redis_available: bool
    delivery_worker_online: bool
    webhook_worker_online: bool
    maintenance_worker_online: bool
    pending_deliveries: int
    delayed_deliveries: int
    failed_deliveries_24h: int
    oldest_pending_at: datetime | None
    pending_inbox_events: int = 0
    delayed_inbox_events: int = 0
    failed_inbox_events_24h: int = 0
    pending_provider_events: int = 0
    failed_provider_events: int = 0
    oldest_pending_event_at: datetime | None = None
    webhook_reconcile: WebhookReconcileRuntimeResponse
    history_reconcile: HistoryReconcileRuntimeResponse
    stale_connected_channels: int = 0
    connected_channels: int
    total_channels: int
    issues: list[str]
    channels: list[OperationalChannelHealth]


class WebhookReconcileRequest(BaseModel):
    channel_id: UUID | None = None
    limit_per_channel: int = Field(default=500, ge=1, le=1000)


class WebhookReconcileResponse(BaseModel):
    channel_id: UUID | None = None
    scanned_channels: int
    checked_events: int
    resolved_events: int
    remaining_pending_events: int
    oldest_pending_event_at: datetime | None = None


class HistoryReconcileRequest(BaseModel):
    channel_id: UUID | None = None
    limit_per_channel: int = Field(default=20, ge=1, le=50)


class HistoryReconcileResponse(BaseModel):
    channel_id: UUID | None = None
    scanned_channels: int
    checked_threads: int
    requested_threads: int
    failed_threads: int
