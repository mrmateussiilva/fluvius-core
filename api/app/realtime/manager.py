from collections import defaultdict
from dataclasses import dataclass
from uuid import UUID

from fastapi import WebSocket

from app.config import settings


@dataclass(frozen=True)
class ConnectionScope:
    user_id: UUID
    channel_ids: frozenset[UUID] | None


class RealtimeManager:
    def __init__(self) -> None:
        self._connections: dict[
            UUID,
            dict[WebSocket, ConnectionScope],
        ] = defaultdict(dict)

    async def connect(
        self,
        tenant_id: UUID,
        websocket: WebSocket,
        *,
        user_id: UUID,
        subprotocol: str | None = None,
        channel_ids: frozenset[UUID] | None = None,
    ) -> None:
        await websocket.accept(subprotocol=subprotocol)
        self._connections[tenant_id][websocket] = ConnectionScope(
            user_id=user_id,
            channel_ids=channel_ids,
        )

    def disconnect(self, tenant_id: UUID, websocket: WebSocket) -> None:
        connections = self._connections.get(tenant_id)
        if connections is None:
            return
        connections.pop(websocket, None)
        if not connections:
            self._connections.pop(tenant_id, None)

    async def broadcast(self, tenant_id: UUID, event: str, data: dict) -> None:
        if settings.environment == "test":
            await self.broadcast_local(tenant_id, event, data)
            return
        from app.realtime.broker import emit_realtime_event

        await emit_realtime_event(tenant_id, event, data)

    async def broadcast_local(self, tenant_id: UUID, event: str, data: dict) -> None:
        stale: list[WebSocket] = []
        connections = self._connections.get(tenant_id, {}).copy()
        raw_channel_id = data.get("channel_id")
        try:
            event_channel_id = (
                UUID(str(raw_channel_id))
                if raw_channel_id is not None
                else None
            )
        except ValueError:
            event_channel_id = None
        for websocket, scope in connections.items():
            allowed_channel_ids = scope.channel_ids
            if allowed_channel_ids is not None and (
                event_channel_id is None
                or event_channel_id not in allowed_channel_ids
            ):
                continue
            try:
                await websocket.send_json({"event": event, "data": data})
            except RuntimeError:
                stale.append(websocket)
        for websocket in stale:
            self.disconnect(tenant_id, websocket)

    async def disconnect_user(self, tenant_id: UUID, user_id: UUID) -> None:
        if settings.environment == "test":
            await self.disconnect_user_local(tenant_id, user_id)
            return
        from app.realtime.broker import emit_disconnect_user

        await emit_disconnect_user(tenant_id, user_id)

    async def disconnect_user_local(self, tenant_id: UUID, user_id: UUID) -> None:
        connections = self._connections.get(tenant_id, {}).copy()
        for websocket, scope in connections.items():
            if scope.user_id != user_id:
                continue
            try:
                await websocket.close(code=1008)
            except RuntimeError:
                pass
            finally:
                self.disconnect(tenant_id, websocket)

    async def disconnect_tenant(self, tenant_id: UUID) -> None:
        if settings.environment == "test":
            await self.disconnect_tenant_local(tenant_id)
            return
        from app.realtime.broker import emit_disconnect_tenant

        await emit_disconnect_tenant(tenant_id)

    async def disconnect_tenant_local(self, tenant_id: UUID) -> None:
        connections = self._connections.get(tenant_id, {}).copy()
        for websocket in connections:
            try:
                await websocket.close(code=1008)
            except RuntimeError:
                pass
            finally:
                self.disconnect(tenant_id, websocket)


realtime_manager = RealtimeManager()
