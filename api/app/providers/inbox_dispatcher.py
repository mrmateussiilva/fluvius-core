import asyncio
import logging
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from redis.exceptions import RedisError
from rq.exceptions import InvalidJobOperation, NoSuchJobError
from rq.job import Job, JobStatus
from sqlalchemy import select

from app.config import settings
from app.database import SessionLocal
from app.jobs.queue import redis_connection, webhook_queue
from app.providers.inbox_tasks import TERMINAL_INBOX_ERROR
from app.providers.models import ProviderEvent, ProviderEventInbox
from app.tenants.models import Tenant

logger = logging.getLogger(__name__)
ENQUEUED_STALE_AFTER = timedelta(minutes=10)
ENQUEUED_JOB_GRACE = timedelta(seconds=15)
PROCESSING_STALE_AFTER = timedelta(minutes=2)
DISPATCHER_LOCK_KEY = "fluvius:webhook-inbox-dispatcher-lock"
DISPATCHER_LOCK_TTL_SECONDS = 8
ACTIVE_RQ_JOB_STATUSES = {
    JobStatus.CREATED,
    JobStatus.QUEUED,
    JobStatus.STARTED,
    JobStatus.DEFERRED,
    JobStatus.SCHEDULED,
}


def dispatch_provider_event_inbox(inbox_id: UUID, tenant_id: UUID) -> bool:
    if settings.environment == "test":
        return False

    rq_job_id = f"webhook-inbox-{inbox_id}-{uuid4()}"
    with SessionLocal() as db:
        inbox = db.scalar(
            select(ProviderEventInbox)
            .where(
                ProviderEventInbox.id == inbox_id,
                ProviderEventInbox.tenant_id == tenant_id,
                ProviderEventInbox.status.in_(("queued", "retry_wait")),
            )
            .with_for_update(skip_locked=True)
        )
        if inbox is None:
            return False
        now = datetime.now(UTC)
        if inbox.next_attempt_at and inbox.next_attempt_at > now:
            return False
        inbox.status = "enqueued"
        inbox.rq_job_id = rq_job_id
        db.commit()

    try:
        webhook_queue.enqueue(
            "app.providers.inbox_tasks.run_provider_event_inbox",
            str(inbox_id),
            str(tenant_id),
            job_id=rq_job_id,
            job_timeout=120,
            result_ttl=3600,
            failure_ttl=86400,
        )
        return True
    except Exception:
        with SessionLocal() as db:
            inbox = db.scalar(
                select(ProviderEventInbox)
                .where(
                    ProviderEventInbox.id == inbox_id,
                    ProviderEventInbox.tenant_id == tenant_id,
                    ProviderEventInbox.status == "enqueued",
                    ProviderEventInbox.rq_job_id == rq_job_id,
                )
                .with_for_update()
            )
            if inbox is not None:
                inbox.status = "queued"
                inbox.rq_job_id = None
                db.commit()
        logger.warning("Inbox de webhook persistida; o enqueue será repetido")
        return False


def dispatch_due_provider_events(tenant_id: UUID, limit: int = 100) -> int:
    now = datetime.now(UTC)
    with SessionLocal() as db:
        stale_processing = list(
            db.scalars(
                select(ProviderEventInbox)
                .where(
                    ProviderEventInbox.tenant_id == tenant_id,
                    ProviderEventInbox.status == "processing",
                    ProviderEventInbox.locked_at < now - PROCESSING_STALE_AFTER,
                )
                .with_for_update(skip_locked=True)
            )
        )
        for inbox in stale_processing:
            if inbox.attempt_count >= inbox.max_attempts:
                inbox.status = "failed"
                inbox.completed_at = now
                event = db.scalar(
                    select(ProviderEvent).where(
                        ProviderEvent.id == inbox.provider_event_id,
                        ProviderEvent.tenant_id == tenant_id,
                    )
                )
                if event is not None:
                    event.processing_error = TERMINAL_INBOX_ERROR
            else:
                inbox.status = "retry_wait"
                inbox.next_attempt_at = now
            inbox.locked_at = None
            inbox.rq_job_id = None
            inbox.last_error = "Worker interrompido durante o processamento"

        enqueued_candidates = list(
            db.scalars(
                select(ProviderEventInbox)
                .where(
                    ProviderEventInbox.tenant_id == tenant_id,
                    ProviderEventInbox.status == "enqueued",
                    ProviderEventInbox.updated_at < now - ENQUEUED_JOB_GRACE,
                )
                .with_for_update(skip_locked=True)
            )
        )
        for inbox in enqueued_candidates:
            is_expired = inbox.updated_at < now - ENQUEUED_STALE_AFTER
            if not is_expired and _rq_job_is_active(inbox.rq_job_id):
                continue
            inbox.status = "queued"
            inbox.rq_job_id = None

        db.flush()
        due_ids = list(
            db.scalars(
                select(ProviderEventInbox.id)
                .where(
                    ProviderEventInbox.tenant_id == tenant_id,
                    ProviderEventInbox.status.in_(("queued", "retry_wait")),
                    ProviderEventInbox.next_attempt_at <= now,
                )
                .order_by(
                    ProviderEventInbox.next_attempt_at,
                    ProviderEventInbox.created_at,
                )
                .limit(limit)
            )
        )
        db.commit()

    return sum(
        dispatch_provider_event_inbox(inbox_id, tenant_id) for inbox_id in due_ids
    )


async def provider_inbox_dispatcher_loop(stop_event: asyncio.Event) -> None:
    while not stop_event.is_set():
        lock_token = None
        try:
            lock_token = await asyncio.to_thread(_claim_dispatcher_lock)
            if lock_token:
                tenant_ids = await asyncio.to_thread(_tenant_ids)
                for tenant_id in tenant_ids:
                    await asyncio.to_thread(dispatch_due_provider_events, tenant_id)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.warning("Dispatcher da inbox repetirá a varredura")
        finally:
            if lock_token:
                await asyncio.to_thread(_release_dispatcher_lock, lock_token)
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=2)
        except TimeoutError:
            pass


def _claim_dispatcher_lock() -> str | None:
    token = str(uuid4())
    try:
        claimed = redis_connection.set(
            DISPATCHER_LOCK_KEY,
            token,
            nx=True,
            ex=DISPATCHER_LOCK_TTL_SECONDS,
        )
    except RedisError:
        return None
    return token if claimed else None


def _release_dispatcher_lock(token: str) -> None:
    try:
        redis_connection.eval(
            "if redis.call('get', KEYS[1]) == ARGV[1] then "
            "return redis.call('del', KEYS[1]) else return 0 end",
            1,
            DISPATCHER_LOCK_KEY,
            token,
        )
    except RedisError:
        return


def _tenant_ids() -> list[UUID]:
    with SessionLocal() as db:
        return list(db.scalars(select(Tenant.id).order_by(Tenant.id)))


def _rq_job_is_active(job_id: str | None) -> bool:
    if not job_id:
        return False
    try:
        job = Job.fetch(job_id, connection=redis_connection)
        return job.get_status(refresh=True) in ACTIVE_RQ_JOB_STATUSES
    except (InvalidJobOperation, NoSuchJobError):
        return False
    except RedisError:
        return True
