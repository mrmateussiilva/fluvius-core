from collections import defaultdict
from uuid import UUID

from fastapi import WebSocket


class RealtimeManager:
    def __init__(self) -> None:
        self._connections: dict[UUID, set[WebSocket]] = defaultdict(set)

    async def connect(self, tenant_id: UUID, websocket: WebSocket) -> None:
        await websocket.accept()
        self._connections[tenant_id].add(websocket)

    def disconnect(self, tenant_id: UUID, websocket: WebSocket) -> None:
        connections = self._connections.get(tenant_id)
        if connections is None:
            return
        connections.discard(websocket)
        if not connections:
            self._connections.pop(tenant_id, None)

    async def broadcast(self, tenant_id: UUID, event: str, data: dict) -> None:
        stale: list[WebSocket] = []
        for websocket in self._connections.get(tenant_id, set()).copy():
            try:
                await websocket.send_json({"event": event, "data": data})
            except RuntimeError:
                stale.append(websocket)
        for websocket in stale:
            self.disconnect(tenant_id, websocket)


realtime_manager = RealtimeManager()
