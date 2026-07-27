import asyncio
import logging
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import select

from app.config import settings
from app.conversations.models import Conversation
from app.database import SessionLocal
from app.delivery.models import MessageDelivery
from app.delivery.tasks import fail_stale_delivery
from app.jobs.queue import delivery_queue
from app.messages.models import Message
from app.realtime.broker import publish_realtime_event
from app.tenants.models import Tenant


logger = logging.getLogger(__name__)
ENQUEUED_STALE_AFTER = timedelta(minutes=10)
PROCESSING_STALE_AFTER = timedelta(minutes=2)


def create_delivery(
    *,
    tenant_id: UUID,
    message_id: UUID,
    now: datetime | None = None,
) -> MessageDelivery:
    return MessageDelivery(
        tenant_id=tenant_id,
        message_id=message_id,
        status="queued",
        next_attempt_at=now or datetime.now(UTC),
    )


def dispatch_delivery(delivery_id: UUID, tenant_id: UUID) -> bool:
    if settings.environment == "test":
        return False

    rq_job_id = f"delivery-{delivery_id}-{uuid4()}"
    with SessionLocal() as db:
        delivery = db.scalar(
            select(MessageDelivery)
            .where(
                MessageDelivery.id == delivery_id,
                MessageDelivery.tenant_id == tenant_id,
                MessageDelivery.status.in_(("queued", "retry_wait")),
            )
            .with_for_update(skip_locked=True)
        )
        if delivery is None:
            return False
        now = datetime.now(UTC)
        if delivery.next_attempt_at and delivery.next_attempt_at > now:
            return False
        delivery.status = "enqueued"
        delivery.rq_job_id = rq_job_id
        db.commit()

    try:
        delivery_queue.enqueue(
            "app.delivery.tasks.run_delivery",
            str(delivery_id),
            str(tenant_id),
            job_id=rq_job_id,
            job_timeout=90,
            result_ttl=3600,
            failure_ttl=86400,
        )
        return True
    except Exception:
        with SessionLocal() as db:
            delivery = db.scalar(
                select(MessageDelivery)
                .where(
                    MessageDelivery.id == delivery_id,
                    MessageDelivery.tenant_id == tenant_id,
                    MessageDelivery.status == "enqueued",
                    MessageDelivery.rq_job_id == rq_job_id,
                )
                .with_for_update()
            )
            if delivery is not None:
                delivery.status = "queued"
                delivery.rq_job_id = None
                db.commit()
        logger.warning("Não foi possível enfileirar uma entrega; a outbox tentará novamente")
        return False


def dispatch_due_deliveries(tenant_id: UUID, limit: int = 100) -> int:
    now = datetime.now(UTC)
    stale_messages: list[tuple[Message, UUID | None]] = []
    with SessionLocal() as db:
        stale_processing = list(
            db.scalars(
                select(MessageDelivery)
                .where(
                    MessageDelivery.tenant_id == tenant_id,
                    MessageDelivery.status == "processing",
                    MessageDelivery.locked_at < now - PROCESSING_STALE_AFTER,
                )
                .with_for_update(skip_locked=True)
            )
        )
        for delivery in stale_processing:
            message = fail_stale_delivery(db, delivery, tenant_id)
            if message is not None:
                channel_id = db.scalar(
                    select(Conversation.channel_id).where(
                        Conversation.id == message.conversation_id,
                        Conversation.tenant_id == tenant_id,
                    )
                )
                stale_messages.append((message, channel_id))

        stale_enqueued = list(
            db.scalars(
                select(MessageDelivery)
                .where(
                    MessageDelivery.tenant_id == tenant_id,
                    MessageDelivery.status == "enqueued",
                    MessageDelivery.updated_at < now - ENQUEUED_STALE_AFTER,
                )
                .with_for_update(skip_locked=True)
            )
        )
        for delivery in stale_enqueued:
            delivery.status = "queued"
            delivery.rq_job_id = None

        due_ids = list(
            db.scalars(
                select(MessageDelivery.id)
                .where(
                    MessageDelivery.tenant_id == tenant_id,
                    MessageDelivery.status.in_(("queued", "retry_wait")),
                    MessageDelivery.next_attempt_at <= now,
                )
                .order_by(MessageDelivery.next_attempt_at, MessageDelivery.created_at)
                .limit(limit)
            )
        )
        db.commit()

    for message, channel_id in stale_messages:
        event_data = {
            "id": str(message.id),
            "conversation_id": str(message.conversation_id),
        }
        if channel_id is not None:
            event_data["channel_id"] = str(channel_id)
        publish_realtime_event(
            tenant_id,
            "message.updated",
            event_data,
        )
    return sum(
        dispatch_delivery(delivery_id, tenant_id) for delivery_id in due_ids
    )


async def delivery_dispatcher_loop(stop_event: asyncio.Event) -> None:
    while not stop_event.is_set():
        try:
            tenant_ids = await asyncio.to_thread(_tenant_ids)
            for tenant_id in tenant_ids:
                await asyncio.to_thread(dispatch_due_deliveries, tenant_id)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.warning("Dispatcher de entregas repetirá a varredura")
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=2)
        except TimeoutError:
            pass


def _tenant_ids() -> list[UUID]:
    with SessionLocal() as db:
        return list(db.scalars(select(Tenant.id).order_by(Tenant.id)))
