import asyncio
import logging
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.channels.models import WhatsAppChannel
from app.common.audit_models import AuditLog
from app.common.enums import ChannelProvider, ChannelStatus, ContactKind
from app.contacts.models import Contact
from app.contacts.service import import_channel_groups, synchronize_contact_profile
from app.conversations.models import Conversation
from app.database import SessionLocal
from app.jobs.runtime import prepare_job_runtime
from app.providers.base import IgnoredWebhookEvent, IncomingMessageEditResult
from app.providers.evolution_credentials import (
    ProviderConfigurationError,
    claim_evolution_credential,
)
from app.providers.factory import get_provider
from app.providers.models import ProviderEvent
from app.providers.pending_events import PENDING_MESSAGE_ERRORS, PENDING_RECEIPT_ERROR
from app.providers.status_updates import apply_message_status_update
from app.providers.webhook_router import apply_message_edit
from app.sync.models import SyncRun

CONTACT_SYNC_LIMIT = 50
MESSAGE_SYNC_LIMIT = 500
logger = logging.getLogger(__name__)
CONTACT_OFFLINE_ERROR = "O canal foi desconectado durante a sincronização."
CONTACT_FAILURE_ERROR = "Não foi possível atualizar um dos perfis de contato."
MESSAGE_FAILURE_ERROR = "Um evento de mensagem ainda não pôde ser reconciliado."
FATAL_SYNC_ERROR = "A sincronização foi interrompida por uma falha interna segura."


def run_sync(sync_run_id: str, tenant_id: str) -> None:
    prepare_job_runtime()
    run_id = UUID(sync_run_id)
    scoped_tenant_id = UUID(tenant_id)
    try:
        asyncio.run(_run_sync(run_id, scoped_tenant_id))
    except Exception:
        logger.exception(
            "Falha interna na sincronização %s do tenant %s",
            run_id,
            scoped_tenant_id,
        )
        try:
            _mark_fatal_failure(run_id, scoped_tenant_id)
        except Exception:
            logger.exception(
                "Não foi possível persistir a falha da sincronização %s do tenant %s",
                run_id,
                scoped_tenant_id,
            )
        raise


async def _run_sync(run_id: UUID, tenant_id: UUID) -> None:
    with SessionLocal() as db:
        run = _get_run(db, run_id, tenant_id, for_update=True)
        if run is None or run.status != "queued":
            return
        channel = db.scalar(
            select(WhatsAppChannel).where(
                WhatsAppChannel.id == run.channel_id,
                WhatsAppChannel.tenant_id == tenant_id,
            )
        )
        if channel is None:
            run.status = "failed"
            run.error = "Canal não encontrado para esta sincronização."
            run.finished_at = datetime.now(UTC)
            db.add(
                AuditLog(
                    tenant_id=tenant_id,
                    user_id=run.requested_by_user_id,
                    action="sync.failed",
                    entity_type="sync_run",
                    entity_id=run.id,
                    metadata_={
                        "channel_id": str(run.channel_id),
                        "sync_type": run.sync_type,
                        "channel_missing": True,
                    },
                )
            )
            db.commit()
            return

        run.status = "running"
        run.started_at = datetime.now(UTC)
        contact_items: list[tuple[UUID, ContactKind]] = []
        if run.sync_type in {"contacts", "all"}:
            contact_items = _contact_items(
                db,
                tenant_id,
                channel.id,
            )
        contact_ids = [contact_id for contact_id, _kind in contact_items]
        event_ids = (
            _message_event_ids(
                db,
                tenant_id,
                channel.id,
                recent_days=run.recent_days,
            )
            if run.sync_type in {"messages", "all"}
            else []
        )
        run.contact_items = sum(
            1 for _contact_id, kind in contact_items if kind == ContactKind.DIRECT
        )
        run.group_items = sum(1 for _contact_id, kind in contact_items if kind == ContactKind.GROUP)
        run.message_event_items = len(event_ids)
        run.total_items = len(contact_ids) + len(event_ids)
        db.commit()

        if (
            run.sync_type in {"contacts", "all"}
            and channel.provider == ChannelProvider.EVOLUTION_GO
        ):
            try:
                imported_groups = await import_channel_groups(db, channel=channel)
                run.imported_group_items = len(imported_groups)
                db.commit()
            except (ProviderConfigurationError, NotImplementedError):
                pass

    for contact_id in contact_ids:
        await _synchronize_contact(run_id, tenant_id, contact_id)
    for event_id in event_ids:
        await _reconcile_message_event(run_id, tenant_id, event_id)
    _finish_run(run_id, tenant_id)


def _contact_items(
    db: Session,
    tenant_id: UUID,
    channel_id: UUID,
) -> list[tuple[UUID, ContactKind]]:
    rows = db.execute(
        select(Conversation.contact_id, Contact.kind)
        .join(
            Contact,
            (Contact.id == Conversation.contact_id) & (Contact.tenant_id == tenant_id),
        )
        .where(
            Conversation.tenant_id == tenant_id,
            Conversation.channel_id == channel_id,
            Contact.kind.in_((ContactKind.DIRECT, ContactKind.GROUP)),
        )
        .order_by(Conversation.last_message_at.desc().nullslast())
        .limit(CONTACT_SYNC_LIMIT)
    )
    return [(contact_id, kind) for contact_id, kind in rows]


def _message_event_ids(
    db: Session,
    tenant_id: UUID,
    channel_id: UUID,
    *,
    recent_days: int,
) -> list[UUID]:
    cutoff = datetime.now(UTC) - timedelta(days=recent_days)
    return list(
        db.scalars(
            select(ProviderEvent.id)
            .where(
                ProviderEvent.tenant_id == tenant_id,
                ProviderEvent.channel_id == channel_id,
                ProviderEvent.processed.is_(False),
                ProviderEvent.created_at >= cutoff,
                or_(
                    ProviderEvent.processing_error == PENDING_MESSAGE_ERRORS[0],
                    ProviderEvent.processing_error == PENDING_MESSAGE_ERRORS[1],
                ),
            )
            .order_by(ProviderEvent.created_at)
            .limit(MESSAGE_SYNC_LIMIT)
        )
    )


async def _synchronize_contact(
    run_id: UUID,
    tenant_id: UUID,
    contact_id: UUID,
) -> None:
    with SessionLocal() as db:
        run = _get_run(db, run_id, tenant_id)
        if run is None or run.status != "running":
            return
        channel = db.scalar(
            select(WhatsAppChannel).where(
                WhatsAppChannel.id == run.channel_id,
                WhatsAppChannel.tenant_id == tenant_id,
            )
        )
        contact = db.scalar(
            select(Contact)
            .join(
                Conversation,
                (Conversation.contact_id == Contact.id) & (Conversation.tenant_id == tenant_id),
            )
            .where(
                Contact.id == contact_id,
                Contact.tenant_id == tenant_id,
                Conversation.channel_id == run.channel_id,
            )
        )
        if channel is None or contact is None:
            _record_item(db, run, success=False, error=CONTACT_FAILURE_ERROR)
            db.commit()
            return
        if channel.status != ChannelStatus.CONNECTED:
            contact.profile_sync_error = CONTACT_OFFLINE_ERROR
            _record_item(db, run, success=False, error=CONTACT_OFFLINE_ERROR)
            db.commit()
            return

        try:
            profile = await synchronize_contact_profile(
                db,
                channel=channel,
                contact=contact,
            )
            if profile.error:
                _record_item(db, run, success=False, error=profile.error)
            else:
                _record_item(db, run, success=True)
            db.commit()
        except (ProviderConfigurationError, NotImplementedError):
            db.rollback()
            _record_contact_failure(
                db,
                run_id,
                tenant_id,
                contact_id,
                CONTACT_FAILURE_ERROR,
            )
        except Exception:
            db.rollback()
            _record_contact_failure(
                db,
                run_id,
                tenant_id,
                contact_id,
                CONTACT_FAILURE_ERROR,
            )


def _record_contact_failure(
    db: Session,
    run_id: UUID,
    tenant_id: UUID,
    contact_id: UUID,
    error: str,
) -> None:
    run = _get_run(db, run_id, tenant_id, for_update=True)
    contact = db.scalar(
        select(Contact).where(
            Contact.id == contact_id,
            Contact.tenant_id == tenant_id,
        )
    )
    if run is None or run.status != "running":
        return
    if contact is not None:
        contact.profile_sync_error = error
    _record_item(db, run, success=False, error=error)
    db.commit()


async def _reconcile_message_event(
    run_id: UUID,
    tenant_id: UUID,
    event_id: UUID,
) -> None:
    with SessionLocal() as db:
        run = _get_run(db, run_id, tenant_id)
        if run is None or run.status != "running":
            return
        channel = db.scalar(
            select(WhatsAppChannel).where(
                WhatsAppChannel.id == run.channel_id,
                WhatsAppChannel.tenant_id == tenant_id,
            )
        )
        event = db.scalar(
            select(ProviderEvent)
            .where(
                ProviderEvent.id == event_id,
                ProviderEvent.tenant_id == tenant_id,
                ProviderEvent.channel_id == run.channel_id,
            )
            .with_for_update()
        )
        if channel is None or event is None:
            _record_item(db, run, success=False, error=MESSAGE_FAILURE_ERROR)
            db.commit()
            return
        if event.processed:
            _record_item(db, run, success=True)
            db.commit()
            return

        now = datetime.now(UTC)
        stale_cutoff = now - timedelta(minutes=15)
        try:
            if channel.provider == ChannelProvider.EVOLUTION_GO:
                claim_evolution_credential(db, channel)
            adapter = get_provider(channel.provider, channel, db)
            if event.processing_error == PENDING_RECEIPT_ERROR:
                try:
                    update = adapter.handle_message_status(event.payload)
                except IgnoredWebhookEvent:
                    event.processed = True
                    event.processing_error = None
                    update = None
                if update is not None:
                    application = apply_message_status_update(
                        db,
                        tenant_id=tenant_id,
                        channel_id=channel.id,
                        update=update,
                    )
                    if application.covers(update.provider_message_ids):
                        event.processed = True
                        event.processing_error = None
                    elif event.created_at < stale_cutoff:
                        event.processed = True
                        event.processing_error = "Recibo para mensagem não localizada no canal"
            else:
                try:
                    incoming = await adapter.handle_webhook(event.payload)
                except IgnoredWebhookEvent:
                    event.processed = True
                    event.processing_error = None
                    incoming = None
                if isinstance(incoming, IncomingMessageEditResult):
                    apply_message_edit(
                        db,
                        channel=channel,
                        event=event,
                        edit=incoming,
                    )
                    if not event.processed and event.created_at < stale_cutoff:
                        event.processed = True
                        event.processing_error = "Edição para mensagem original não localizada"
            success = event.processed
            _record_item(
                db,
                run,
                success=success,
                error=None if success else MESSAGE_FAILURE_ERROR,
            )
            db.commit()
        except (
            IgnoredWebhookEvent,
            NotImplementedError,
            ProviderConfigurationError,
            ValueError,
        ):
            db.rollback()
            _record_event_failure(db, run_id, tenant_id, MESSAGE_FAILURE_ERROR)
        except Exception:
            db.rollback()
            _record_event_failure(db, run_id, tenant_id, MESSAGE_FAILURE_ERROR)


def _record_event_failure(
    db: Session,
    run_id: UUID,
    tenant_id: UUID,
    error: str,
) -> None:
    run = _get_run(db, run_id, tenant_id, for_update=True)
    if run is None or run.status != "running":
        return
    _record_item(db, run, success=False, error=error)
    db.commit()


def _record_item(
    db: Session,
    run: SyncRun,
    *,
    success: bool,
    error: str | None = None,
) -> None:
    run.processed_items += 1
    if success:
        run.succeeded_items += 1
    else:
        run.failed_items += 1
        if error and not run.error:
            run.error = error[:500]


def _finish_run(run_id: UUID, tenant_id: UUID) -> None:
    with SessionLocal() as db:
        run = _get_run(db, run_id, tenant_id, for_update=True)
        if run is None or run.status != "running":
            return
        if run.failed_items == 0:
            run.status = "completed"
            run.error = None
        elif run.succeeded_items == 0:
            run.status = "failed"
        else:
            run.status = "partial"
        run.finished_at = datetime.now(UTC)
        db.add(
            AuditLog(
                tenant_id=tenant_id,
                user_id=run.requested_by_user_id,
                action=f"sync.{run.status}",
                entity_type="sync_run",
                entity_id=run.id,
                metadata_={
                    "channel_id": str(run.channel_id),
                    "sync_type": run.sync_type,
                    "total_items": run.total_items,
                    "contact_items": run.contact_items,
                    "group_items": run.group_items,
                    "message_event_items": run.message_event_items,
                    "imported_group_items": run.imported_group_items,
                    "succeeded_items": run.succeeded_items,
                    "failed_items": run.failed_items,
                },
            )
        )
        db.commit()


def _mark_fatal_failure(run_id: UUID, tenant_id: UUID) -> None:
    with SessionLocal() as db:
        run = _get_run(db, run_id, tenant_id, for_update=True)
        if run is None or run.status not in {"queued", "running"}:
            return
        run.status = "failed"
        run.error = FATAL_SYNC_ERROR
        run.finished_at = datetime.now(UTC)
        db.add(
            AuditLog(
                tenant_id=tenant_id,
                user_id=run.requested_by_user_id,
                action="sync.failed",
                entity_type="sync_run",
                entity_id=run.id,
                metadata_={
                    "channel_id": str(run.channel_id),
                    "sync_type": run.sync_type,
                    "fatal": True,
                },
            )
        )
        db.commit()


def _get_run(
    db: Session,
    run_id: UUID,
    tenant_id: UUID,
    *,
    for_update: bool = False,
) -> SyncRun | None:
    query = select(SyncRun).where(
        SyncRun.id == run_id,
        SyncRun.tenant_id == tenant_id,
    )
    if for_update:
        query = query.with_for_update()
    return db.scalar(query)
