import asyncio
import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from redis.exceptions import RedisError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.channels.models import WhatsAppChannel
from app.common.enums import ChannelProvider
from app.config import settings
from app.database import SessionLocal
from app.jobs.queue import redis_connection
from app.providers.base import IgnoredWebhookEvent, IncomingMessageEditResult
from app.providers.evolution_credentials import (
    ProviderConfigurationError,
    claim_evolution_credential,
)
from app.providers.factory import get_provider
from app.providers.inbox_tasks import run_provider_event_inbox
from app.providers.models import ProviderEvent, ProviderEventInbox
from app.providers.pending_events import (
    PENDING_EDIT_ERROR,
    PENDING_INCOMING_MESSAGE_ERROR,
    PENDING_MESSAGE_ERRORS,
    PENDING_RECEIPT_ERROR,
)
from app.providers.status_updates import apply_message_status_update
from app.providers.webhook_router import apply_message_edit, whatsapp_webhook

logger = logging.getLogger(__name__)
RECONCILE_LOCK_KEY = "fluvius:webhook-reconcile-lock"
RECONCILE_HEARTBEAT_KEY = "fluvius:webhook-reconcile-heartbeat"
RECONCILE_STATS_KEY = "fluvius:webhook-reconcile-stats"
RECONCILE_LOCK_TTL_SECONDS = 45
RECONCILE_BATCH_PER_CHANNEL = 40
RECONCILE_MAX_AGE = timedelta(days=7)
RECONCILE_LOOP_SECONDS = 30
RECONCILE_HEARTBEAT_TTL_SECONDS = RECONCILE_LOOP_SECONDS * 3


@dataclass(frozen=True)
class WebhookReconcileRuntime:
    active: bool
    heartbeat_at: datetime | None = None
    last_started_at: datetime | None = None
    last_finished_at: datetime | None = None
    last_error_at: datetime | None = None
    last_error: str | None = None
    last_scanned_channels: int = 0
    last_checked_events: int = 0
    last_resolved_events: int = 0


@dataclass(frozen=True)
class WebhookReconcileChannelResult:
    checked_events: int = 0
    resolved_events: int = 0


@dataclass(frozen=True)
class WebhookReconcileBatchResult:
    scanned_channels: int = 0
    checked_events: int = 0
    resolved_events: int = 0


async def webhook_reconcile_loop(stop_event: asyncio.Event) -> None:
    while not stop_event.is_set():
        try:
            await asyncio.to_thread(_record_reconcile_heartbeat)
            if await asyncio.to_thread(_claim_reconcile_lock):
                try:
                    await asyncio.to_thread(_record_reconcile_started)
                    result = await _run_reconcile_batch()
                    await asyncio.to_thread(_record_reconcile_finished, result)
                finally:
                    await asyncio.to_thread(_release_reconcile_lock)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            await asyncio.to_thread(_record_reconcile_error, exc)
            logger.warning("Reconcile de webhooks pendentes repetirá a varredura")
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=RECONCILE_LOOP_SECONDS)
        except TimeoutError:
            pass


async def reconcile_pending_events_for_channel(
    db: Session,
    *,
    tenant_id: UUID,
    channel_id: UUID,
    limit: int = RECONCILE_BATCH_PER_CHANNEL,
) -> int:
    result = await reconcile_pending_events_for_channel_report(
        db,
        tenant_id=tenant_id,
        channel_id=channel_id,
        limit=limit,
    )
    return result.resolved_events


async def reconcile_pending_events_for_channel_report(
    db: Session,
    *,
    tenant_id: UUID,
    channel_id: UUID,
    limit: int = RECONCILE_BATCH_PER_CHANNEL,
) -> WebhookReconcileChannelResult:
    channel = db.scalar(
        select(WhatsAppChannel).where(
            WhatsAppChannel.id == channel_id,
            WhatsAppChannel.tenant_id == tenant_id,
        )
    )
    if channel is None:
        return WebhookReconcileChannelResult()
    cutoff = datetime.now(UTC) - RECONCILE_MAX_AGE
    events = list(
        db.scalars(
            select(ProviderEvent)
            .where(
                ProviderEvent.tenant_id == tenant_id,
                ProviderEvent.channel_id == channel_id,
                ProviderEvent.processed.is_(False),
                ProviderEvent.created_at >= cutoff,
                ProviderEvent.processing_error.in_(PENDING_MESSAGE_ERRORS),
            )
            .order_by(ProviderEvent.created_at)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
    )
    if not events:
        return WebhookReconcileChannelResult()
    try:
        if channel.provider == ChannelProvider.EVOLUTION_GO:
            claim_evolution_credential(db, channel)
        adapter = get_provider(channel.provider, channel, db)
    except ProviderConfigurationError:
        return WebhookReconcileChannelResult(checked_events=len(events))

    resolved = 0
    for event in events:
        event_id = event.id
        try:
            if event.processing_error == PENDING_INCOMING_MESSAGE_ERROR:
                inbox = db.scalar(
                    select(ProviderEventInbox).where(
                        ProviderEventInbox.tenant_id == tenant_id,
                        ProviderEventInbox.provider_event_id == event.id,
                    )
                )
                if inbox is None:
                    await whatsapp_webhook(
                        provider=channel.provider,
                        channel_id=channel.id,
                        payload=event.payload,
                        x_webhook_secret=settings.webhook_secret,
                        db=db,
                    )
                    inbox = db.scalar(
                        select(ProviderEventInbox).where(
                            ProviderEventInbox.tenant_id == tenant_id,
                            ProviderEventInbox.provider_event_id == event_id,
                        )
                    )
                if inbox is not None:
                    db.commit()
                    await asyncio.to_thread(
                        run_provider_event_inbox,
                        str(inbox.id),
                        str(tenant_id),
                    )
                    db.expire_all()
                refreshed_event = db.get(ProviderEvent, event_id)
                if refreshed_event is not None and refreshed_event.processed:
                    resolved += 1
                continue

            if event.processing_error == PENDING_RECEIPT_ERROR:
                update = adapter.handle_message_status(event.payload)
                if update is None:
                    continue
                application = apply_message_status_update(
                    db,
                    tenant_id=tenant_id,
                    channel_id=channel.id,
                    update=update,
                )
                if application.covers(update.provider_message_ids):
                    event.processed = True
                    event.processing_error = None
                    resolved += 1
                continue

            if event.processing_error == PENDING_EDIT_ERROR:
                inbox = db.scalar(
                    select(ProviderEventInbox).where(
                        ProviderEventInbox.tenant_id == tenant_id,
                        ProviderEventInbox.provider_event_id == event.id,
                        ProviderEventInbox.normalized_kind == "edit",
                    )
                )
                incoming = (
                    IncomingMessageEditResult.model_validate(
                        inbox.normalized_payload
                    )
                    if inbox is not None
                    else await adapter.handle_webhook(event.payload)
                )
                if isinstance(incoming, IncomingMessageEditResult):
                    edited = apply_message_edit(
                        db,
                        channel=channel,
                        event=event,
                        edit=incoming,
                    )
                    if edited is not None and event.processed:
                        resolved += 1
        except (IgnoredWebhookEvent, ValueError, NotImplementedError):
            continue
        except Exception:
            logger.warning(
                "Falha ao reconciliar evento %s do canal %s",
                event.id,
                channel_id,
            )
            db.rollback()
            return WebhookReconcileChannelResult(
                checked_events=len(events),
                resolved_events=resolved,
            )
    db.commit()
    return WebhookReconcileChannelResult(
        checked_events=len(events),
        resolved_events=resolved,
    )


async def _run_reconcile_batch() -> WebhookReconcileBatchResult:
    checked_events = 0
    resolved_events = 0
    with SessionLocal() as db:
        channels = list(
            db.execute(
                select(
                    WhatsAppChannel.tenant_id,
                    WhatsAppChannel.id,
                )
                .join(
                    ProviderEvent,
                    (ProviderEvent.channel_id == WhatsAppChannel.id)
                    & (ProviderEvent.tenant_id == WhatsAppChannel.tenant_id),
                )
                .where(
                    ProviderEvent.processed.is_(False),
                    ProviderEvent.processing_error.in_(PENDING_MESSAGE_ERRORS),
                    ProviderEvent.created_at >= datetime.now(UTC) - RECONCILE_MAX_AGE,
                )
                .group_by(WhatsAppChannel.tenant_id, WhatsAppChannel.id)
                .limit(50)
            )
        )
    for tenant_id, channel_id in channels:
        with SessionLocal() as db:
            result = await reconcile_pending_events_for_channel_report(
                db,
                tenant_id=tenant_id,
                channel_id=channel_id,
            )
            checked_events += result.checked_events
            resolved_events += result.resolved_events
    return WebhookReconcileBatchResult(
        scanned_channels=len(channels),
        checked_events=checked_events,
        resolved_events=resolved_events,
    )


def get_webhook_reconcile_runtime() -> WebhookReconcileRuntime:
    try:
        raw_heartbeat = redis_connection.get(RECONCILE_HEARTBEAT_KEY)
        raw_stats = redis_connection.hgetall(RECONCILE_STATS_KEY)
    except RedisError:
        return WebhookReconcileRuntime(active=False)

    heartbeat = _decode_datetime(raw_heartbeat)
    stats = {
        _decode_text(key): _decode_text(value)
        for key, value in raw_stats.items()
    }
    return WebhookReconcileRuntime(
        active=heartbeat is not None,
        heartbeat_at=heartbeat,
        last_started_at=_decode_datetime(stats.get("last_started_at")),
        last_finished_at=_decode_datetime(stats.get("last_finished_at")),
        last_error_at=_decode_datetime(stats.get("last_error_at")),
        last_error=stats.get("last_error") or None,
        last_scanned_channels=_decode_int(stats.get("last_scanned_channels")),
        last_checked_events=_decode_int(stats.get("last_checked_events")),
        last_resolved_events=_decode_int(stats.get("last_resolved_events")),
    )


def reset_failed_provider_inbox_for_channel(
    db: Session,
    *,
    tenant_id: UUID,
    channel_id: UUID,
    limit: int,
) -> int:
    failed_rows = list(
        db.execute(
            select(ProviderEventInbox, ProviderEvent)
            .join(
                ProviderEvent,
                (ProviderEvent.id == ProviderEventInbox.provider_event_id)
                & (ProviderEvent.tenant_id == tenant_id),
            )
            .where(
                ProviderEventInbox.tenant_id == tenant_id,
                ProviderEventInbox.status == "failed",
                ProviderEvent.tenant_id == tenant_id,
                ProviderEvent.channel_id == channel_id,
                ProviderEvent.processed.is_(False),
            )
            .order_by(ProviderEventInbox.created_at)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
    )
    now = datetime.now(UTC)
    for inbox, event in failed_rows:
        inbox.status = "queued"
        inbox.attempt_count = 0
        inbox.next_attempt_at = now
        inbox.locked_at = None
        inbox.rq_job_id = None
        inbox.last_error = None
        inbox.completed_at = None
        event.processing_error = PENDING_INCOMING_MESSAGE_ERROR
    if failed_rows:
        db.commit()
    return len(failed_rows)


def _claim_reconcile_lock() -> bool:
    try:
        return bool(
            redis_connection.set(
                RECONCILE_LOCK_KEY,
                "1",
                nx=True,
                ex=RECONCILE_LOCK_TTL_SECONDS,
            )
        )
    except RedisError:
        return False


def _release_reconcile_lock() -> None:
    try:
        redis_connection.delete(RECONCILE_LOCK_KEY)
    except RedisError:
        return


def _record_reconcile_heartbeat() -> None:
    try:
        redis_connection.set(
            RECONCILE_HEARTBEAT_KEY,
            datetime.now(UTC).isoformat(),
            ex=RECONCILE_HEARTBEAT_TTL_SECONDS,
        )
    except RedisError:
        return


def _record_reconcile_started() -> None:
    try:
        redis_connection.hset(
            RECONCILE_STATS_KEY,
            mapping={"last_started_at": datetime.now(UTC).isoformat()},
        )
    except RedisError:
        return


def _record_reconcile_finished(result: WebhookReconcileBatchResult) -> None:
    try:
        redis_connection.hset(
            RECONCILE_STATS_KEY,
            mapping={
                "last_finished_at": datetime.now(UTC).isoformat(),
                "last_scanned_channels": str(result.scanned_channels),
                "last_checked_events": str(result.checked_events),
                "last_resolved_events": str(result.resolved_events),
                "last_error": "",
            },
        )
    except RedisError:
        return


def _record_reconcile_error(exc: Exception) -> None:
    try:
        redis_connection.hset(
            RECONCILE_STATS_KEY,
            mapping={
                "last_error_at": datetime.now(UTC).isoformat(),
                "last_error": exc.__class__.__name__,
            },
        )
    except RedisError:
        return


def _decode_text(value: object) -> str:
    if isinstance(value, bytes):
        return value.decode()
    return str(value or "")


def _decode_datetime(value: object) -> datetime | None:
    if value is None:
        return None
    raw = _decode_text(value)
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


def _decode_int(value: object) -> int:
    try:
        return int(_decode_text(value))
    except ValueError:
        return 0
