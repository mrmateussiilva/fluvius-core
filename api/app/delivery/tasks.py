import asyncio
import logging
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.channels.models import WhatsAppChannel
from app.common.enums import (
    ChannelProvider,
    ChannelStatus,
    MessageDirection,
    MessageStatus,
)
from app.contacts.models import Contact
from app.conversations.models import Conversation
from app.database import SessionLocal
from app.delivery.models import MessageDelivery
from app.delivery.order import has_pending_predecessor
from app.delivery.service import (
    apply_send_result,
    call_provider,
    reconcile_delivery_receipts,
    safe_delivery_error,
)
from app.jobs.runtime import prepare_job_runtime
from app.messages.models import Message
from app.providers.evolution_credentials import (
    ProviderConfigurationError,
    claim_evolution_credential,
)
from app.realtime.broker import publish_realtime_event


RETRY_DELAYS_SECONDS = (5, 30, 120)
logger = logging.getLogger(__name__)
SAFE_INTERNAL_ERROR = (
    "O envio foi interrompido antes de receber uma confirmação segura."
)
AMBIGUOUS_RECOVERY_ERROR = (
    "O worker foi interrompido durante o envio. O reenvio automático foi "
    "bloqueado para evitar duplicidade."
)


def run_delivery(delivery_id: str, tenant_id: str) -> None:
    prepare_job_runtime()
    scoped_delivery_id = UUID(delivery_id)
    scoped_tenant_id = UUID(tenant_id)
    try:
        asyncio.run(_run_delivery(scoped_delivery_id, scoped_tenant_id))
    except Exception:
        logger.exception(
            "Falha interna na entrega %s do tenant %s",
            scoped_delivery_id,
            scoped_tenant_id,
        )
        try:
            _mark_internal_failure(scoped_delivery_id, scoped_tenant_id)
        except Exception:
            logger.exception(
                "Não foi possível persistir a falha da entrega %s do tenant %s",
                scoped_delivery_id,
                scoped_tenant_id,
            )
        raise


async def _run_delivery(delivery_id: UUID, tenant_id: UUID) -> None:
    with SessionLocal() as db:
        delivery = _get_delivery(
            db,
            delivery_id,
            tenant_id,
            for_update=True,
        )
        if delivery is None or delivery.status not in {
            "queued",
            "enqueued",
            "retry_wait",
        }:
            return
        now = datetime.now(UTC)
        if delivery.next_attempt_at and delivery.next_attempt_at > now:
            return

        message = db.scalar(
            select(Message).where(
                Message.id == delivery.message_id,
                Message.tenant_id == tenant_id,
            )
        )
        if (
            message is None
            or message.direction != MessageDirection.OUTGOING
            or message.status != MessageStatus.PENDING
        ):
            delivery.status = "failed"
            delivery.last_error = "Mensagem não está disponível para entrega."
            delivery.completed_at = now
            delivery.locked_at = None
            db.commit()
            return

        conversation = db.scalar(
            select(Conversation).where(
                Conversation.id == message.conversation_id,
                Conversation.tenant_id == tenant_id,
            )
        )
        if conversation is None:
            _fail_delivery(
                delivery,
                message,
                "Conversa não encontrada para esta mensagem.",
            )
            db.commit()
            _publish_message(message)
            return

        if has_pending_predecessor(db, message):
            delivery.status = "retry_wait"
            delivery.next_attempt_at = now + timedelta(seconds=2)
            delivery.locked_at = None
            db.commit()
            return

        channel = db.scalar(
            select(WhatsAppChannel).where(
                WhatsAppChannel.id == conversation.channel_id,
                WhatsAppChannel.tenant_id == tenant_id,
            )
        )
        contact = db.scalar(
            select(Contact).where(
                Contact.id == conversation.contact_id,
                Contact.tenant_id == tenant_id,
            )
        )
        if channel is None or contact is None:
            _fail_delivery(
                delivery,
                message,
                "Canal ou contato não encontrado para esta mensagem.",
            )
            db.commit()
            _publish_message(message, channel_id=conversation.channel_id)
            return
        if channel.status != ChannelStatus.CONNECTED:
            _fail_delivery(
                delivery,
                message,
                "WhatsApp desconectado durante o processamento do envio.",
            )
            db.commit()
            _publish_message(message, channel_id=conversation.channel_id)
            return

        try:
            if channel.provider == ChannelProvider.EVOLUTION_GO:
                claim_evolution_credential(db, channel)
        except ProviderConfigurationError:
            _fail_delivery(
                delivery,
                message,
                "A credencial do canal não está disponível para envio.",
            )
            db.commit()
            _publish_message(message, channel_id=conversation.channel_id)
            return

        delivery.status = "processing"
        delivery.locked_at = now
        delivery.attempt_count += 1
        message.attempt_count += 1
        message.last_attempt_at = now
        db.commit()  # Persist the attempt before the provider side effect.

        result = await call_provider(
            db,
            message=message,
            channel=channel,
            contact=contact,
        )
        if (
            not result.success
            and result.retryable
            and delivery.attempt_count < delivery.max_attempts
        ):
            retry_index = min(
                delivery.attempt_count - 1,
                len(RETRY_DELAYS_SECONDS) - 1,
            )
            delivery.status = "retry_wait"
            delivery.next_attempt_at = datetime.now(UTC) + timedelta(
                seconds=RETRY_DELAYS_SECONDS[retry_index]
            )
            delivery.locked_at = None
            delivery.last_error = safe_delivery_error(
                result.error,
                "Falha temporária no provider.",
            )
            message.status = MessageStatus.PENDING
            message.error = None
            db.commit()
            _publish_message(message, channel_id=conversation.channel_id)
            return

        apply_send_result(message, result)
        if message.status == MessageStatus.SENT:
            delivery.status = "completed"
            delivery.last_error = None
        else:
            delivery.status = "failed"
            delivery.last_error = safe_delivery_error(
                message.error,
                "O provider não confirmou o envio.",
            )
        delivery.completed_at = datetime.now(UTC)
        delivery.locked_at = None
        delivery.next_attempt_at = None
        reconciled = (
            reconcile_delivery_receipts(
                db,
                channel=channel,
                message=message,
            )
            if message.status == MessageStatus.SENT
            else []
        )
        db.commit()
        _publish_message(message, channel_id=conversation.channel_id)
        for updated in reconciled:
            if updated.id != message.id:
                _publish_message(updated, channel_id=conversation.channel_id)


def fail_stale_delivery(
    db: Session,
    delivery: MessageDelivery,
    tenant_id: UUID,
) -> Message | None:
    message = db.scalar(
        select(Message).where(
            Message.id == delivery.message_id,
            Message.tenant_id == tenant_id,
            Message.status == MessageStatus.PENDING,
        )
    )
    delivery.status = "failed"
    delivery.last_error = AMBIGUOUS_RECOVERY_ERROR
    delivery.completed_at = datetime.now(UTC)
    delivery.locked_at = None
    delivery.next_attempt_at = None
    if message is not None:
        message.status = MessageStatus.FAILED
        message.error = AMBIGUOUS_RECOVERY_ERROR
    return message


def _fail_delivery(
    delivery: MessageDelivery,
    message: Message,
    error: str,
) -> None:
    safe_error = safe_delivery_error(error, SAFE_INTERNAL_ERROR)
    delivery.status = "failed"
    delivery.last_error = safe_error
    delivery.completed_at = datetime.now(UTC)
    delivery.locked_at = None
    delivery.next_attempt_at = None
    message.status = MessageStatus.FAILED
    message.error = safe_error
    message.sent_at = None


def _mark_internal_failure(delivery_id: UUID, tenant_id: UUID) -> None:
    with SessionLocal() as db:
        delivery = _get_delivery(
            db,
            delivery_id,
            tenant_id,
            for_update=True,
        )
        if delivery is None or delivery.status in {"completed", "failed"}:
            return
        message = db.scalar(
            select(Message).where(
                Message.id == delivery.message_id,
                Message.tenant_id == tenant_id,
            )
        )
        delivery.status = "failed"
        delivery.last_error = SAFE_INTERNAL_ERROR
        delivery.completed_at = datetime.now(UTC)
        delivery.locked_at = None
        delivery.next_attempt_at = None
        if message is not None and message.status == MessageStatus.PENDING:
            message.status = MessageStatus.FAILED
            message.error = SAFE_INTERNAL_ERROR
        db.commit()
        if message is not None:
            conversation_channel_id = db.scalar(
                select(Conversation.channel_id).where(
                    Conversation.id == message.conversation_id,
                    Conversation.tenant_id == tenant_id,
                )
            )
            _publish_message(message, channel_id=conversation_channel_id)


def _get_delivery(
    db: Session,
    delivery_id: UUID,
    tenant_id: UUID,
    *,
    for_update: bool = False,
) -> MessageDelivery | None:
    query = select(MessageDelivery).where(
        MessageDelivery.id == delivery_id,
        MessageDelivery.tenant_id == tenant_id,
    )
    if for_update:
        query = query.with_for_update()
    return db.scalar(query)


def _publish_message(
    message: Message,
    *,
    channel_id: UUID | None = None,
) -> None:
    data = {
        "id": str(message.id),
        "conversation_id": str(message.conversation_id),
    }
    if channel_id is not None:
        data["channel_id"] = str(channel_id)
    publish_realtime_event(
        message.tenant_id,
        "message.updated",
        data,
    )
