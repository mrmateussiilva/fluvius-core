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


def publish_realtime_event(
    tenant_id: UUID,
    event: str,
    data: dict[str, Any],
) -> bool:
    if settings.environment == "test":
        return True
    payload = json.dumps(
        {
            "tenant_id": str(tenant_id),
            "event": event,
            "data": data,
        },
        separators=(",", ":"),
    )
    try:
        connection = Redis.from_url(
            settings.redis_url,
            socket_connect_timeout=1,
            socket_timeout=2,
        )
        connection.publish(REALTIME_CHANNEL, payload)
        connection.close()
        return True
    except Exception:
        logger.warning("Não foi possível publicar um evento realtime no Redis")
        return False


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
                tenant_id = UUID(parsed["tenant_id"])
                event = parsed["event"]
                data = parsed["data"]
                if isinstance(event, str) and isinstance(data, dict):
                    await realtime_manager.broadcast(tenant_id, event, data)
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
