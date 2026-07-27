import asyncio
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.channels.models import WhatsAppChannel
from app.common.audit_models import AuditLog
from app.common.enums import ChannelProvider, ChannelStatus
from app.contacts.models import Contact
from app.contacts.service import synchronize_contact_profile
from app.conversations.models import Conversation
from app.database import SessionLocal
from app.providers.base import IgnoredWebhookEvent, IncomingMessageEditResult
from app.providers.evolution_credentials import (
    ProviderConfigurationError,
    claim_evolution_credential,
)
from app.providers.factory import get_provider
from app.providers.models import ProviderEvent
from app.providers.status_updates import apply_message_status_update
from app.providers.webhook_router import apply_message_edit
from app.sync.models import SyncRun


CONTACT_SYNC_LIMIT = 50
MESSAGE_SYNC_LIMIT = 500
PENDING_MESSAGE_ERRORS = (
    "Aguardando a mensagem correspondente ser confirmada pelo provider",
    "Aguardando a mensagem original da edição ser persistida",
)
CONTACT_OFFLINE_ERROR = "O canal foi desconectado durante a sincronização."
CONTACT_FAILURE_ERROR = "Não foi possível atualizar um dos perfis de contato."
MESSAGE_FAILURE_ERROR = "Um evento de mensagem ainda não pôde ser reconciliado."
FATAL_SYNC_ERROR = "A sincronização foi interrompida por uma falha interna segura."


def run_sync(sync_run_id: str, tenant_id: str) -> None:
    run_id = UUID(sync_run_id)
    scoped_tenant_id = UUID(tenant_id)
    try:
        asyncio.run(_run_sync(run_id, scoped_tenant_id))
    except Exception:
        _mark_fatal_failure(run_id, scoped_tenant_id)


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
        contact_ids = (
            _contact_ids(db, tenant_id, channel.id)
            if run.sync_type in {"contacts", "all"}
            else []
        )
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
        run.total_items = len(contact_ids) + len(event_ids)
        db.commit()

    for contact_id in contact_ids:
        await _synchronize_contact(run_id, tenant_id, contact_id)
    for event_id in event_ids:
        await _reconcile_message_event(run_id, tenant_id, event_id)
    _finish_run(run_id, tenant_id)


def _contact_ids(db: Session, tenant_id: UUID, channel_id: UUID) -> list[UUID]:
    return list(
        db.scalars(
            select(Conversation.contact_id)
            .where(
                Conversation.tenant_id == tenant_id,
                Conversation.channel_id == channel_id,
            )
            .order_by(Conversation.last_message_at.desc().nullslast())
            .limit(CONTACT_SYNC_LIMIT)
        )
    )


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
                (Conversation.contact_id == Contact.id)
                & (Conversation.tenant_id == tenant_id),
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

        try:
            if channel.provider == ChannelProvider.EVOLUTION_GO:
                claim_evolution_credential(db, channel)
            adapter = get_provider(channel.provider, channel, db)
            if event.processing_error == PENDING_MESSAGE_ERRORS[0]:
                update = adapter.handle_message_status(event.payload)
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
            else:
                incoming = await adapter.handle_webhook(event.payload)
                if isinstance(incoming, IncomingMessageEditResult):
                    apply_message_edit(
                        db,
                        channel=channel,
                        event=event,
                        edit=incoming,
                    )
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
