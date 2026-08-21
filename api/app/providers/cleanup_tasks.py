import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete

from app.database import SessionLocal
from app.jobs.runtime import prepare_job_runtime
from app.providers.models import ProviderEvent, ProviderEventInbox

logger = logging.getLogger(__name__)


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
    logger.info(
        "Limpeza de eventos concluída: %d inboxes e %d eventos removidos (retenção: %d dias)",
        deleted_inbox,
        deleted_events,
        retention_days,
    )
    return total
