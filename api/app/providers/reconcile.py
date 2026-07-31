import asyncio
import logging
from datetime import UTC, datetime, timedelta
from uuid import UUID

from redis.exceptions import RedisError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.channels.models import WhatsAppChannel
from app.common.enums import ChannelProvider
from app.database import SessionLocal
from app.jobs.queue import redis_connection
from app.providers.base import IgnoredWebhookEvent, IncomingMessageEditResult
from app.providers.evolution_credentials import (
    ProviderConfigurationError,
    claim_evolution_credential,
)
from app.providers.factory import get_provider
from app.providers.models import ProviderEvent
from app.providers.pending_events import PENDING_EDIT_ERROR, PENDING_RECEIPT_ERROR
from app.providers.status_updates import apply_message_status_update
from app.providers.webhook_router import apply_message_edit


logger = logging.getLogger(__name__)
RECONCILE_LOCK_KEY = "fluvius:webhook-reconcile-lock"
RECONCILE_LOCK_TTL_SECONDS = 45
RECONCILE_BATCH_PER_CHANNEL = 40
RECONCILE_MAX_AGE = timedelta(days=7)
RECONCILE_LOOP_SECONDS = 30


async def webhook_reconcile_loop(stop_event: asyncio.Event) -> None:
    while not stop_event.is_set():
        try:
            if await asyncio.to_thread(_claim_reconcile_lock):
                try:
                    await _run_reconcile_batch()
                finally:
                    await asyncio.to_thread(_release_reconcile_lock)
        except asyncio.CancelledError:
            raise
        except Exception:
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
    channel = db.scalar(
        select(WhatsAppChannel).where(
            WhatsAppChannel.id == channel_id,
            WhatsAppChannel.tenant_id == tenant_id,
        )
    )
    if channel is None:
        return 0
    cutoff = datetime.now(UTC) - RECONCILE_MAX_AGE
    events = list(
        db.scalars(
            select(ProviderEvent)
            .where(
                ProviderEvent.tenant_id == tenant_id,
                ProviderEvent.channel_id == channel_id,
                ProviderEvent.processed.is_(False),
                ProviderEvent.created_at >= cutoff,
                ProviderEvent.processing_error.in_(
                    (PENDING_RECEIPT_ERROR, PENDING_EDIT_ERROR)
                ),
            )
            .order_by(ProviderEvent.created_at)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
    )
    if not events:
        return 0
    try:
        if channel.provider == ChannelProvider.EVOLUTION_GO:
            claim_evolution_credential(db, channel)
        adapter = get_provider(channel.provider, channel, db)
    except ProviderConfigurationError:
        return 0

    resolved = 0
    for event in events:
        try:
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
                incoming = await adapter.handle_webhook(event.payload)
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
            return resolved
    db.commit()
    return resolved


async def _run_reconcile_batch() -> int:
    total = 0
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
                    ProviderEvent.processing_error.in_(
                        (PENDING_RECEIPT_ERROR, PENDING_EDIT_ERROR)
                    ),
                    ProviderEvent.created_at >= datetime.now(UTC) - RECONCILE_MAX_AGE,
                )
                .group_by(WhatsAppChannel.tenant_id, WhatsAppChannel.id)
                .limit(50)
            )
        )
    for tenant_id, channel_id in channels:
        with SessionLocal() as db:
            total += await reconcile_pending_events_for_channel(
                db,
                tenant_id=tenant_id,
                channel_id=channel_id,
            )
    return total


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
