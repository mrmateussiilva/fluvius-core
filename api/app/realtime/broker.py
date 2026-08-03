import asyncio
import json
import logging
from typing import Any
from uuid import UUID

from redis import Redis
from redis.asyncio import Redis as AsyncRedis

from app.config import settings
from app.realtime.manager import realtime_manager

logger = logging.getLogger(__name__)
REALTIME_CHANNEL = "fluvius:realtime"


def _event_payload(
    tenant_id: UUID,
    event: str,
    data: dict[str, Any],
) -> dict[str, Any]:
    return {
        "kind": "event",
        "tenant_id": str(tenant_id),
        "event": event,
        "data": data,
    }


def publish_realtime_event(
    tenant_id: UUID,
    event: str,
    data: dict[str, Any],
) -> bool:
    if settings.environment == "test":
        return True
    payload = json.dumps(
        _event_payload(tenant_id, event, data),
        separators=(",", ":"),
    )
    connection: Redis | None = None
    try:
        connection = Redis.from_url(
            settings.redis_url,
            socket_connect_timeout=1,
            socket_timeout=2,
        )
        return connection.publish(REALTIME_CHANNEL, payload) > 0
    except Exception:
        logger.warning("Não foi possível publicar um evento realtime no Redis")
        return False
    finally:
        if connection is not None:
            connection.close()


async def _publish_realtime_payload(payload: dict[str, Any]) -> bool:
    connection: AsyncRedis | None = None
    try:
        connection = AsyncRedis.from_url(
            settings.redis_url,
            socket_connect_timeout=1,
            socket_timeout=2,
            decode_responses=True,
        )
        subscribers = await connection.publish(
            REALTIME_CHANNEL,
            json.dumps(payload, separators=(",", ":")),
        )
        return subscribers > 0
    except Exception:
        logger.warning("Não foi possível publicar um evento realtime no Redis")
        return False
    finally:
        if connection is not None:
            try:
                await connection.aclose()
            except Exception:
                pass


async def emit_realtime_event(
    tenant_id: UUID,
    event: str,
    data: dict[str, Any],
) -> bool:
    if settings.environment == "test":
        await realtime_manager.broadcast_local(tenant_id, event, data)
        return True
    published = await _publish_realtime_payload(
        _event_payload(tenant_id, event, data)
    )
    if not published:
        await realtime_manager.broadcast_local(tenant_id, event, data)
    return published


async def emit_disconnect_user(tenant_id: UUID, user_id: UUID) -> bool:
    if settings.environment == "test":
        await realtime_manager.disconnect_user_local(tenant_id, user_id)
        return True
    published = await _publish_realtime_payload(
        {
            "kind": "disconnect_user",
            "tenant_id": str(tenant_id),
            "user_id": str(user_id),
        }
    )
    if not published:
        await realtime_manager.disconnect_user_local(tenant_id, user_id)
    return published


async def emit_disconnect_tenant(tenant_id: UUID) -> bool:
    if settings.environment == "test":
        await realtime_manager.disconnect_tenant_local(tenant_id)
        return True
    published = await _publish_realtime_payload(
        {
            "kind": "disconnect_tenant",
            "tenant_id": str(tenant_id),
        }
    )
    if not published:
        await realtime_manager.disconnect_tenant_local(tenant_id)
    return published


async def dispatch_realtime_payload(parsed: dict[str, Any]) -> None:
    tenant_id = UUID(parsed["tenant_id"])
    kind = parsed.get("kind", "event")
    if kind == "disconnect_user":
        await realtime_manager.disconnect_user_local(
            tenant_id,
            UUID(parsed["user_id"]),
        )
        return
    if kind == "disconnect_tenant":
        await realtime_manager.disconnect_tenant_local(tenant_id)
        return
    event = parsed.get("event")
    data = parsed.get("data")
    if isinstance(event, str) and isinstance(data, dict):
        await realtime_manager.broadcast_local(tenant_id, event, data)


async def consume_realtime_events(stop_event: asyncio.Event) -> None:
    while not stop_event.is_set():
        connection: AsyncRedis | None = None
        pubsub = None
        try:
            connection = AsyncRedis.from_url(
                settings.redis_url,
                socket_connect_timeout=1,
                socket_timeout=2,
                decode_responses=True,
            )
            pubsub = connection.pubsub()
            await pubsub.subscribe(REALTIME_CHANNEL)
            while not stop_event.is_set():
                item = await pubsub.get_message(
                    ignore_subscribe_messages=True,
                    timeout=1,
                )
                if not item:
                    continue
                parsed = json.loads(item["data"])
                if isinstance(parsed, dict):
                    await dispatch_realtime_payload(parsed)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.warning("Listener realtime do Redis será reconectado")
            await asyncio.sleep(1)
        finally:
            if pubsub is not None:
                try:
                    await pubsub.aclose()
                except Exception:
                    pass
            if connection is not None:
                try:
                    await connection.aclose()
                except Exception:
                    pass
