import asyncio
import logging
from datetime import UTC, datetime, timedelta

from redis.exceptions import RedisError
from sqlalchemy import delete

from app.database import SessionLocal
from app.jobs.queue import redis_connection
from app.jobs.runtime import prepare_job_runtime
from app.providers.models import ProviderEvent, ProviderEventInbox

logger = logging.getLogger(__name__)

CLEANUP_LOCK_KEY = "fluvius:cleanup-tasks-lock"
CLEANUP_LOCK_TTL_SECONDS = 300
CLEANUP_LOOP_INTERVAL_SECONDS = 3600 * 6  # Executa a cada 6 horas


def cleanup_old_processed_events(retention_days: int = 30) -> int:
    """Safely cleans up old completed/processed webhook events to keep tables fast."""
    prepare_job_runtime()
    cutoff = datetime.now(UTC) - timedelta(days=retention_days)
    with SessionLocal() as db:
        deleted_inbox = db.execute(
            delete(ProviderEventInbox).where(
                ProviderEventInbox.status == "completed",
                ProviderEventInbox.completed_at < cutoff,
            )
        ).rowcount

        deleted_events = db.execute(
            delete(ProviderEvent).where(
                ProviderEvent.processed.is_(True),
                ProviderEvent.created_at < cutoff,
            )
        ).rowcount

        db.commit()

    total = deleted_inbox + deleted_events
    if total > 0:
        logger.info(
            "Limpeza de eventos concluída: %d inboxes e %d eventos removidos (retenção: %d dias)",
            deleted_inbox,
            deleted_events,
            retention_days,
        )
    return total


def _claim_cleanup_lock() -> bool:
    try:
        return bool(
            redis_connection.set(
                CLEANUP_LOCK_KEY,
                "1",
                nx=True,
                ex=CLEANUP_LOCK_TTL_SECONDS,
            )
        )
    except RedisError:
        return False


def _release_cleanup_lock() -> None:
    try:
        redis_connection.delete(CLEANUP_LOCK_KEY)
    except RedisError:
        return


async def cleanup_scheduler_loop(stop_event: asyncio.Event) -> None:
    while not stop_event.is_set():
        try:
            if await asyncio.to_thread(_claim_cleanup_lock):
                try:
                    await asyncio.to_thread(cleanup_old_processed_events, retention_days=30)
                finally:
                    await asyncio.to_thread(_release_cleanup_lock)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.warning("Erro no agendador de limpeza automática; repetirá no próximo ciclo")
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=CLEANUP_LOOP_INTERVAL_SECONDS)
        except TimeoutError:
            pass
