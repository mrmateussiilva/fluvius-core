from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from redis.exceptions import RedisError
from rq import Worker
from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from app.auth.dependencies import AuthContext, get_auth_context
from app.channels.models import WhatsAppChannel
from app.common.enums import ChannelStatus, MessageStatus
from app.database import get_db
from app.delivery.models import MessageDelivery
from app.jobs.queue import (
    delivery_queue,
    maintenance_queue,
    redis_connection,
)
from app.messages.models import Message
from app.operations.schemas import (
    OperationalChannelHealth,
    OperationalHealthResponse,
    OperationalStatus,
)
from app.providers.models import ProviderEvent
from app.providers.pending_events import PENDING_MESSAGE_ERRORS


router = APIRouter(prefix="/operations", tags=["operations"])
DELAYED_DELIVERY_AFTER = timedelta(minutes=2)
FAILED_DELIVERY_WINDOW = timedelta(hours=24)
STALE_CONNECTED_AFTER = timedelta(minutes=30)
DELAYED_PROVIDER_EVENT_AFTER = timedelta(minutes=15)
ACTIVE_DELIVERY_STATUSES = ("queued", "enqueued", "processing", "retry_wait")


def require_admin(
    context: AuthContext = Depends(get_auth_context),
) -> AuthContext:
    if context.membership.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Apenas administradores podem consultar a saúde operacional",
        )
    return context


@router.get("/health", response_model=OperationalHealthResponse)
def operational_health(
    context: AuthContext = Depends(require_admin),
    db: Session = Depends(get_db),
) -> OperationalHealthResponse:
    now = datetime.now(UTC)
    active_delivery_filters = (
        MessageDelivery.tenant_id == context.tenant_id,
        Message.tenant_id == context.tenant_id,
        MessageDelivery.status.in_(ACTIVE_DELIVERY_STATUSES),
        Message.status == MessageStatus.PENDING,
    )
    pending_deliveries = db.scalar(
        select(func.count(MessageDelivery.id))
        .join(
            Message,
            (Message.id == MessageDelivery.message_id)
            & (Message.tenant_id == context.tenant_id),
        )
        .where(*active_delivery_filters)
    ) or 0
    delayed_deliveries = db.scalar(
        select(func.count(MessageDelivery.id))
        .join(
            Message,
            (Message.id == MessageDelivery.message_id)
            & (Message.tenant_id == context.tenant_id),
        )
        .where(
            *active_delivery_filters,
            Message.created_at < now - DELAYED_DELIVERY_AFTER,
        )
    ) or 0
    oldest_pending_at = db.scalar(
        select(func.min(Message.created_at))
        .join(
            MessageDelivery,
            (MessageDelivery.message_id == Message.id)
            & (MessageDelivery.tenant_id == context.tenant_id),
        )
        .where(
            Message.tenant_id == context.tenant_id,
            Message.status == MessageStatus.PENDING,
            MessageDelivery.status.in_(ACTIVE_DELIVERY_STATUSES),
        )
    )
    failed_deliveries_24h = db.scalar(
        select(func.count(MessageDelivery.id)).where(
            MessageDelivery.tenant_id == context.tenant_id,
            MessageDelivery.status == "failed",
            MessageDelivery.completed_at >= now - FAILED_DELIVERY_WINDOW,
        )
    ) or 0

    pending_event_filter = and_(
        ProviderEvent.tenant_id == context.tenant_id,
        ProviderEvent.processed.is_(False),
        ProviderEvent.processing_error.in_(PENDING_MESSAGE_ERRORS),
    )
    failed_event_filter = and_(
        ProviderEvent.tenant_id == context.tenant_id,
        ProviderEvent.processed.is_(False),
        ProviderEvent.processing_error.is_not(None),
        ProviderEvent.processing_error.notin_(PENDING_MESSAGE_ERRORS),
    )
    pending_provider_events = (
        db.scalar(select(func.count(ProviderEvent.id)).where(pending_event_filter)) or 0
    )
    failed_provider_events = (
        db.scalar(select(func.count(ProviderEvent.id)).where(failed_event_filter)) or 0
    )
    oldest_pending_event_at = db.scalar(
        select(func.min(ProviderEvent.created_at)).where(pending_event_filter)
    )

    last_event_at = (
        select(func.max(ProviderEvent.created_at))
        .where(
            ProviderEvent.tenant_id == context.tenant_id,
            ProviderEvent.channel_id == WhatsAppChannel.id,
        )
        .correlate(WhatsAppChannel)
        .scalar_subquery()
    )
    pending_events_sq = (
        select(func.count(ProviderEvent.id))
        .where(
            ProviderEvent.tenant_id == context.tenant_id,
            ProviderEvent.channel_id == WhatsAppChannel.id,
            ProviderEvent.processed.is_(False),
            ProviderEvent.processing_error.in_(PENDING_MESSAGE_ERRORS),
        )
        .correlate(WhatsAppChannel)
        .scalar_subquery()
    )
    failed_events_sq = (
        select(func.count(ProviderEvent.id))
        .where(
            ProviderEvent.tenant_id == context.tenant_id,
            ProviderEvent.channel_id == WhatsAppChannel.id,
            ProviderEvent.processed.is_(False),
            ProviderEvent.processing_error.is_not(None),
            ProviderEvent.processing_error.notin_(PENDING_MESSAGE_ERRORS),
        )
        .correlate(WhatsAppChannel)
        .scalar_subquery()
    )
    channel_rows = db.execute(
        select(
            WhatsAppChannel,
            last_event_at.label("last_event_at"),
            pending_events_sq.label("pending_events"),
            failed_events_sq.label("failed_events"),
        )
        .where(WhatsAppChannel.tenant_id == context.tenant_id)
        .order_by(WhatsAppChannel.name, WhatsAppChannel.id)
    ).all()
    channels = []
    stale_connected_channels = 0
    for channel, event_at, pending_count, failed_count in channel_rows:
        pending_count = int(pending_count or 0)
        failed_count = int(failed_count or 0)
        webhook_stale = (
            channel.status == ChannelStatus.CONNECTED
            and event_at is None
            and channel.updated_at < now - STALE_CONNECTED_AFTER
        )
        if webhook_stale:
            stale_connected_channels += 1
        channels.append(
            OperationalChannelHealth(
                id=channel.id,
                name=channel.name,
                phone_number=channel.phone_number,
                status=channel.status,
                last_event_at=event_at,
                pending_events=pending_count,
                failed_events=failed_count,
                webhook_stale=webhook_stale,
            )
        )
    connected_channels = sum(
        channel.status == ChannelStatus.CONNECTED for channel in channels
    )

    redis_available, delivery_worker_online, maintenance_worker_online = (
        _worker_health()
    )
    issues: list[str] = []
    critical = False
    if not redis_available:
        issues.append("Redis indisponível para consultar e transportar as filas.")
        critical = True
    elif not delivery_worker_online:
        issues.append("Worker de entregas offline; mensagens não serão enviadas.")
        critical = True
    if delayed_deliveries:
        issues.append(
            f"{delayed_deliveries} entrega(s) aguardando há mais de 2 minutos."
        )
        critical = True
    if not maintenance_worker_online:
        issues.append(
            "Worker de manutenção offline; sincronizações não serão processadas."
        )
    if failed_deliveries_24h:
        issues.append(
            f"{failed_deliveries_24h} entrega(s) falharam nas últimas 24 horas."
        )
    if pending_provider_events:
        delayed_pending = (
            oldest_pending_event_at is not None
            and oldest_pending_event_at < now - DELAYED_PROVIDER_EVENT_AFTER
        )
        issues.append(
            f"{pending_provider_events} evento(s) de webhook aguardando reconciliação."
        )
        if delayed_pending:
            critical = True
    if failed_provider_events:
        issues.append(
            f"{failed_provider_events} evento(s) de webhook com erro de processamento."
        )
    if stale_connected_channels:
        issues.append(
            f"{stale_connected_channels} canal(is) conectado(s) sem eventos recentes."
        )
    unavailable_channels = [
        channel
        for channel in channels
        if channel.status != ChannelStatus.CONNECTED
    ]
    if unavailable_channels:
        names = ", ".join(channel.name for channel in unavailable_channels[:3])
        suffix = "…" if len(unavailable_channels) > 3 else ""
        issues.append(f"Canal(is) sem conexão: {names}{suffix}")
        if any(
            channel.status == ChannelStatus.FAILED
            for channel in unavailable_channels
        ):
            critical = True

    health_status: OperationalStatus
    if critical:
        health_status = "critical"
    elif issues:
        health_status = "attention"
    else:
        health_status = "healthy"
    return OperationalHealthResponse(
        status=health_status,
        generated_at=now,
        redis_available=redis_available,
        delivery_worker_online=delivery_worker_online,
        maintenance_worker_online=maintenance_worker_online,
        pending_deliveries=pending_deliveries,
        delayed_deliveries=delayed_deliveries,
        failed_deliveries_24h=failed_deliveries_24h,
        oldest_pending_at=oldest_pending_at,
        pending_provider_events=pending_provider_events,
        failed_provider_events=failed_provider_events,
        oldest_pending_event_at=oldest_pending_event_at,
        stale_connected_channels=stale_connected_channels,
        connected_channels=connected_channels,
        total_channels=len(channels),
        issues=issues,
        channels=channels,
    )


def _worker_health() -> tuple[bool, bool, bool]:
    try:
        redis_connection.ping()
        return (
            True,
            Worker.count(queue=delivery_queue) > 0,
            Worker.count(queue=maintenance_queue) > 0,
        )
    except RedisError:
        return False, False, False
