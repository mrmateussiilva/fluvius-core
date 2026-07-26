from uuid import UUID

import jwt
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, status
from sqlalchemy import select

from app.database import SessionLocal
from app.realtime.manager import realtime_manager
from app.security import decode_access_token
from app.users.models import TenantUser


router = APIRouter()


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    protocols = [
        value.strip()
        for value in websocket.headers.get("sec-websocket-protocol", "").split(",")
        if value.strip()
    ]
    if len(protocols) != 2 or protocols[0] != "fluvius-auth":
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return
    token = protocols[1]
    try:
        payload = decode_access_token(token)
        user_id = UUID(payload["sub"])
        tenant_id = UUID(payload["tenant_id"])
    except (jwt.PyJWTError, KeyError, ValueError):
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    with SessionLocal() as db:
        membership = db.scalar(
            select(TenantUser).where(
                TenantUser.user_id == user_id,
                TenantUser.tenant_id == tenant_id,
                TenantUser.is_active.is_(True),
            )
        )
    if membership is None:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    await realtime_manager.connect(
        tenant_id,
        websocket,
        subprotocol="fluvius-auth",
    )
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        realtime_manager.disconnect(tenant_id, websocket)
