import asyncio
import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from redis.exceptions import RedisError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.channels.models import WhatsAppChannel
from app.common.enums import ChannelProvider, ChannelStatus, ContactKind, MessageDirection
from app.contacts.models import Contact
from app.conversations.models import Conversation
from app.database import SessionLocal
from app.jobs.queue import redis_connection
from app.messages.models import Message
from app.providers.base import MessageHistoryAnchor
from app.providers.evolution_credentials import (
    ProviderConfigurationError,
    claim_evolution_credential,
)
from app.providers.factory import get_provider

logger = logging.getLogger(__name__)

HISTORY_RECONCILE_LOCK_KEY = "fluvius:history-reconcile-lock"
HISTORY_RECONCILE_HEARTBEAT_KEY = "fluvius:history-reconcile-heartbeat"
HISTORY_RECONCILE_STATS_KEY = "fluvius:history-reconcile-stats"
HISTORY_RECONCILE_LOCK_TTL_SECONDS = 240
HISTORY_RECONCILE_LOOP_SECONDS = 300
HISTORY_RECONCILE_HEARTBEAT_TTL_SECONDS = HISTORY_RECONCILE_LOOP_SECONDS * 3
HISTORY_RECONCILE_CONVERSATION_COOLDOWN_SECONDS = 30 * 60
HISTORY_RECONCILE_CHANNEL_LIMIT = 10
HISTORY_RECONCILE_THREADS_PER_CHANNEL = 20
HISTORY_RECONCILE_REQUEST_COUNT = 50
HISTORY_RECONCILE_RECENT_DAYS = 2


@dataclass(frozen=True)
class HistoryReconcileRuntime:
    active: bool
    heartbeat_at: datetime | None = None
    last_started_at: datetime | None = None
    last_finished_at: datetime | None = None
    last_error_at: datetime | None = None
    last_error: str | None = None
    last_scanned_channels: int = 0
    last_checked_threads: int = 0
    last_requested_threads: int = 0
    last_failed_threads: int = 0


@dataclass(frozen=True)
class HistoryReconcileChannelResult:
    checked_threads: int = 0
    requested_threads: int = 0
    failed_threads: int = 0


@dataclass(frozen=True)
class HistoryReconcileBatchResult:
    scanned_channels: int = 0
    checked_threads: int = 0
    requested_threads: int = 0
    failed_threads: int = 0


@dataclass(frozen=True)
class _HistoryThreadCandidate:
    conversation_id: UUID
    provider_message_id: str
    chat_address: str
    is_group: bool
    is_from_me: bool
    timestamp: datetime


async def history_reconcile_loop(stop_event: asyncio.Event) -> None:
    while not stop_event.is_set():
        try:
            await asyncio.to_thread(_record_history_heartbeat)
            if await asyncio.to_thread(_claim_history_lock):
                try:
                    await asyncio.to_thread(_record_history_started)
                    result = await request_history_for_connected_channels_report()
                    await asyncio.to_thread(_record_history_finished, result)
                finally:
                    await asyncio.to_thread(_release_history_lock)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            await asyncio.to_thread(_record_history_error, exc)
            logger.warning("Reconciliador de histórico repetirá a varredura")
        try:
            await asyncio.wait_for(
                stop_event.wait(),
                timeout=HISTORY_RECONCILE_LOOP_SECONDS,
            )
        except TimeoutError:
            pass


async def request_history_for_connected_channels_report(
    *,
    tenant_id: UUID | None = None,
    channel_id: UUID | None = None,
    limit_per_channel: int = HISTORY_RECONCILE_THREADS_PER_CHANNEL,
) -> HistoryReconcileBatchResult:
    with SessionLocal() as db:
        channel_filters = [
            WhatsAppChannel.provider == ChannelProvider.EVOLUTION_GO,
            WhatsAppChannel.status == ChannelStatus.CONNECTED,
        ]
        if tenant_id is not None:
            channel_filters.append(WhatsAppChannel.tenant_id == tenant_id)
        if channel_id is not None:
            channel_filters.append(WhatsAppChannel.id == channel_id)
        channels = list(
            db.scalars(
                select(WhatsAppChannel)
                .where(*channel_filters)
                .order_by(WhatsAppChannel.updated_at.desc())
                .limit(HISTORY_RECONCILE_CHANNEL_LIMIT)
            )
        )

    checked_threads = 0
    requested_threads = 0
    failed_threads = 0
    for channel in channels:
        with SessionLocal() as db:
            result = await request_history_for_channel_report(
                db,
                tenant_id=channel.tenant_id,
                channel_id=channel.id,
                limit=limit_per_channel,
            )
        checked_threads += result.checked_threads
        requested_threads += result.requested_threads
        failed_threads += result.failed_threads

    return HistoryReconcileBatchResult(
        scanned_channels=len(channels),
        checked_threads=checked_threads,
        requested_threads=requested_threads,
        failed_threads=failed_threads,
    )


async def request_history_for_channel_report(
    db: Session,
    *,
    tenant_id: UUID,
    channel_id: UUID,
    limit: int = HISTORY_RECONCILE_THREADS_PER_CHANNEL,
) -> HistoryReconcileChannelResult:
    channel = db.scalar(
        select(WhatsAppChannel).where(
            WhatsAppChannel.id == channel_id,
            WhatsAppChannel.tenant_id == tenant_id,
            WhatsAppChannel.provider == ChannelProvider.EVOLUTION_GO,
        )
    )
    if channel is None or channel.status != ChannelStatus.CONNECTED:
        return HistoryReconcileChannelResult()
    candidates = _thread_candidates(db, tenant_id, channel.id, limit=limit)
    if not candidates:
        return HistoryReconcileChannelResult()

    try:
        claim_evolution_credential(db, channel)
        adapter = get_provider(channel.provider, channel, db)
    except ProviderConfigurationError:
        return HistoryReconcileChannelResult(
            checked_threads=len(candidates),
            failed_threads=len(candidates),
        )

    requested_threads = 0
    failed_threads = 0
    for candidate in candidates:
        if not _claim_thread_cooldown(candidate.conversation_id):
            continue
        anchor = MessageHistoryAnchor(
            provider_message_id=candidate.provider_message_id,
            chat_address=candidate.chat_address,
            is_group=candidate.is_group,
            is_from_me=candidate.is_from_me,
            timestamp=candidate.timestamp,
        )
        result = await adapter.request_message_history(
            channel,
            anchor,
            count=HISTORY_RECONCILE_REQUEST_COUNT,
        )
        if result.success:
            requested_threads += 1
        else:
            failed_threads += 1

    return HistoryReconcileChannelResult(
        checked_threads=len(candidates),
        requested_threads=requested_threads,
        failed_threads=failed_threads,
    )


def get_history_reconcile_runtime() -> HistoryReconcileRuntime:
    try:
        raw_heartbeat = redis_connection.get(HISTORY_RECONCILE_HEARTBEAT_KEY)
        raw_stats = redis_connection.hgetall(HISTORY_RECONCILE_STATS_KEY)
    except RedisError:
        return HistoryReconcileRuntime(active=False)

    heartbeat = _decode_datetime(raw_heartbeat)
    stats = {_decode_text(key): _decode_text(value) for key, value in raw_stats.items()}
    return HistoryReconcileRuntime(
        active=heartbeat is not None,
        heartbeat_at=heartbeat,
        last_started_at=_decode_datetime(stats.get("last_started_at")),
        last_finished_at=_decode_datetime(stats.get("last_finished_at")),
        last_error_at=_decode_datetime(stats.get("last_error_at")),
        last_error=stats.get("last_error") or None,
        last_scanned_channels=_decode_int(stats.get("last_scanned_channels")),
        last_checked_threads=_decode_int(stats.get("last_checked_threads")),
        last_requested_threads=_decode_int(stats.get("last_requested_threads")),
        last_failed_threads=_decode_int(stats.get("last_failed_threads")),
    )


def _thread_candidates(
    db: Session,
    tenant_id: UUID,
    channel_id: UUID,
    *,
    limit: int,
) -> list[_HistoryThreadCandidate]:
    cutoff = datetime.now(UTC) - timedelta(days=HISTORY_RECONCILE_RECENT_DAYS)
    rows = db.execute(
        select(
            Conversation.id,
            Contact.kind,
            Contact.phone_number,
            Contact.provider_address,
            Message.provider_message_id,
            Message.direction,
            Message.sent_at,
            Message.created_at,
        )
        .join(
            Contact,
            (Contact.id == Conversation.contact_id)
            & (Contact.tenant_id == tenant_id),
        )
        .join(
            Message,
            (Message.conversation_id == Conversation.id)
            & (Message.tenant_id == tenant_id),
        )
        .where(
            Conversation.tenant_id == tenant_id,
            Conversation.channel_id == channel_id,
            Conversation.last_message_at >= cutoff,
            Message.provider_message_id.is_not(None),
        )
        .order_by(func.coalesce(Message.sent_at, Message.created_at).desc())
        .limit(limit * 5)
    )
    candidates: list[_HistoryThreadCandidate] = []
    seen_conversations: set[UUID] = set()
    for (
        conversation_id,
        contact_kind,
        phone_number,
        provider_address,
        provider_message_id,
        direction,
        sent_at,
        created_at,
    ) in rows:
        if conversation_id in seen_conversations or not provider_message_id:
            continue
        is_group = contact_kind == ContactKind.GROUP
        chat_address = provider_address if is_group else phone_number
        if not chat_address:
            continue
        seen_conversations.add(conversation_id)
        candidates.append(
            _HistoryThreadCandidate(
                conversation_id=conversation_id,
                provider_message_id=provider_message_id,
                chat_address=chat_address,
                is_group=is_group,
                is_from_me=direction == MessageDirection.OUTGOING,
                timestamp=sent_at or created_at or datetime.now(UTC),
            )
        )
        if len(candidates) >= limit:
            break
    return candidates


def _claim_history_lock() -> bool:
    try:
        return bool(
            redis_connection.set(
                HISTORY_RECONCILE_LOCK_KEY,
                "1",
                nx=True,
                ex=HISTORY_RECONCILE_LOCK_TTL_SECONDS,
            )
        )
    except RedisError:
        return False


def _release_history_lock() -> None:
    try:
        redis_connection.delete(HISTORY_RECONCILE_LOCK_KEY)
    except RedisError:
        return


def _claim_thread_cooldown(conversation_id: UUID) -> bool:
    try:
        return bool(
            redis_connection.set(
                f"fluvius:history-reconcile-thread:{conversation_id}",
                datetime.now(UTC).isoformat(),
                nx=True,
                ex=HISTORY_RECONCILE_CONVERSATION_COOLDOWN_SECONDS,
            )
        )
    except RedisError:
        return False


def _record_history_heartbeat() -> None:
    try:
        redis_connection.set(
            HISTORY_RECONCILE_HEARTBEAT_KEY,
            datetime.now(UTC).isoformat(),
            ex=HISTORY_RECONCILE_HEARTBEAT_TTL_SECONDS,
        )
    except RedisError:
        return


def _record_history_started() -> None:
    try:
        redis_connection.hset(
            HISTORY_RECONCILE_STATS_KEY,
            mapping={"last_started_at": datetime.now(UTC).isoformat()},
        )
    except RedisError:
        return


def _record_history_finished(result: HistoryReconcileBatchResult) -> None:
    try:
        redis_connection.hset(
            HISTORY_RECONCILE_STATS_KEY,
            mapping={
                "last_finished_at": datetime.now(UTC).isoformat(),
                "last_scanned_channels": str(result.scanned_channels),
                "last_checked_threads": str(result.checked_threads),
                "last_requested_threads": str(result.requested_threads),
                "last_failed_threads": str(result.failed_threads),
                "last_error": "",
            },
        )
    except RedisError:
        return


def _record_history_error(exc: Exception) -> None:
    try:
        redis_connection.hset(
            HISTORY_RECONCILE_STATS_KEY,
            mapping={
                "last_error_at": datetime.now(UTC).isoformat(),
                "last_error": exc.__class__.__name__,
            },
        )
    except RedisError:
        return


def _decode_text(value: object) -> str:
    if isinstance(value, bytes):
        return value.decode()
    return str(value or "")


def _decode_datetime(value: object) -> datetime | None:
    if value is None:
        return None
    raw = _decode_text(value)
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


def _decode_int(value: object) -> int:
    try:
        return int(_decode_text(value))
    except ValueError:
        return 0
