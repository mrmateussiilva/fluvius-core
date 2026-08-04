import asyncio
import logging
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select

from app.database import SessionLocal
from app.providers.models import ProviderEvent, ProviderEventInbox
from app.providers.pending_events import PENDING_INCOMING_MESSAGE_ERROR

logger = logging.getLogger(__name__)
RETRY_DELAYS_SECONDS = (5, 15, 30, 60, 120, 300, 600)
TERMINAL_INBOX_ERROR = (
    "Falha ao processar mensagem recebida após as tentativas automáticas"
)


def run_provider_event_inbox(inbox_id: str, tenant_id: str) -> bool:
    parsed_inbox_id = UUID(inbox_id)
    parsed_tenant_id = UUID(tenant_id)
    with SessionLocal() as db:
        inbox = db.scalar(
            select(ProviderEventInbox)
            .where(
                ProviderEventInbox.id == parsed_inbox_id,
                ProviderEventInbox.tenant_id == parsed_tenant_id,
            )
            .with_for_update()
        )
        if inbox is None:
            return False
        if inbox.status == "completed":
            return True
        if inbox.status not in {"queued", "enqueued", "retry_wait"}:
            return False
        if inbox.attempt_count >= inbox.max_attempts:
            inbox.status = "failed"
            inbox.completed_at = datetime.now(UTC)
            event = db.scalar(
                select(ProviderEvent).where(
                    ProviderEvent.id == inbox.provider_event_id,
                    ProviderEvent.tenant_id == parsed_tenant_id,
                )
            )
            if event is not None:
                event.processing_error = TERMINAL_INBOX_ERROR
            db.commit()
            return False
        inbox.status = "processing"
        inbox.attempt_count += 1
        inbox.locked_at = datetime.now(UTC)
        db.commit()

    try:
        return asyncio.run(
            _process_provider_event_inbox(parsed_inbox_id, parsed_tenant_id)
        )
    except Exception as exc:
        _record_processing_failure(parsed_inbox_id, parsed_tenant_id, exc)
        logger.warning(
            "Falha ao processar inbox %s do tenant %s; nova tentativa será agendada",
            parsed_inbox_id,
            parsed_tenant_id,
        )
        return False


async def _process_provider_event_inbox(inbox_id: UUID, tenant_id: UUID) -> bool:
    from app.providers.inbox_processor import process_provider_event_inbox

    return await process_provider_event_inbox(
        inbox_id=inbox_id,
        tenant_id=tenant_id,
    )


def _record_processing_failure(
    inbox_id: UUID,
    tenant_id: UUID,
    exc: Exception,
) -> None:
    with SessionLocal() as db:
        inbox = db.scalar(
            select(ProviderEventInbox)
            .where(
                ProviderEventInbox.id == inbox_id,
                ProviderEventInbox.tenant_id == tenant_id,
                ProviderEventInbox.status == "processing",
            )
            .with_for_update()
        )
        if inbox is None:
            return
        event = db.scalar(
            select(ProviderEvent).where(
                ProviderEvent.id == inbox.provider_event_id,
                ProviderEvent.tenant_id == tenant_id,
            )
        )
        inbox.locked_at = None
        inbox.rq_job_id = None
        inbox.last_error = exc.__class__.__name__
        if inbox.attempt_count >= inbox.max_attempts:
            inbox.status = "failed"
            inbox.completed_at = datetime.now(UTC)
            if event is not None:
                event.processing_error = TERMINAL_INBOX_ERROR
        else:
            retry_index = min(inbox.attempt_count - 1, len(RETRY_DELAYS_SECONDS) - 1)
            inbox.status = "retry_wait"
            inbox.next_attempt_at = datetime.now(UTC) + timedelta(
                seconds=RETRY_DELAYS_SECONDS[retry_index]
            )
            if event is not None:
                event.processing_error = PENDING_INCOMING_MESSAGE_ERROR
        db.commit()
