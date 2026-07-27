from uuid import UUID

import jwt
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, status
from sqlalchemy import select

from app.config import settings
from app.database import SessionLocal
from app.realtime.manager import realtime_manager
from app.security import decode_access_token
from app.users.models import TenantUser, TenantUserChannel


router = APIRouter()


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    origin = websocket.headers.get("origin")
    if (
        settings.environment == "production"
        and origin not in settings.cors_origin_list
    ):
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return
    protocols = [
        value.strip()
        for value in websocket.headers.get("sec-websocket-protocol", "").split(",")
        if value.strip()
    ]
    selected_subprotocol: str | None = None
    token = websocket.cookies.get(settings.auth_cookie_name)
    if len(protocols) == 2 and protocols[0] == "fluvius-auth":
        token = protocols[1]
        selected_subprotocol = "fluvius-auth"
    elif protocols:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return
    if token is None:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return
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
        channel_ids = (
            None
            if membership is not None and membership.role == "admin"
            else frozenset(
                db.scalars(
                    select(TenantUserChannel.channel_id).where(
                        TenantUserChannel.tenant_id == tenant_id,
                        TenantUserChannel.user_id == user_id,
                    )
                )
            )
        )
    if membership is None:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    await realtime_manager.connect(
        tenant_id,
        websocket,
        user_id=user_id,
        subprotocol=selected_subprotocol,
        channel_ids=channel_ids,
    )
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        realtime_manager.disconnect(tenant_id, websocket)
