from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.dependencies import AuthContext, get_auth_context
from app.channels.models import WhatsAppChannel
from app.channels.schemas import ChannelCreate, ChannelResponse
from app.common.enums import ChannelStatus
from app.database import get_db
from app.providers.base import ChannelStatusResult, QRCodeResult
from app.providers.factory import get_provider


router = APIRouter(prefix="/channels", tags=["channels"])


def get_tenant_channel(db: Session, tenant_id: UUID, channel_id: UUID) -> WhatsAppChannel:
    channel = db.scalar(
        select(WhatsAppChannel).where(
            WhatsAppChannel.id == channel_id, WhatsAppChannel.tenant_id == tenant_id
        )
    )
    if channel is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Canal não encontrado")
    return channel


@router.get("", response_model=list[ChannelResponse])
def list_channels(
    context: AuthContext = Depends(get_auth_context), db: Session = Depends(get_db)
) -> list[WhatsAppChannel]:
    return list(
        db.scalars(
            select(WhatsAppChannel)
            .where(WhatsAppChannel.tenant_id == context.tenant_id)
            .order_by(WhatsAppChannel.created_at)
        )
    )


@router.post("", response_model=ChannelResponse, status_code=status.HTTP_201_CREATED)
def create_channel(
    payload: ChannelCreate,
    context: AuthContext = Depends(get_auth_context),
    db: Session = Depends(get_db),
) -> WhatsAppChannel:
    channel = WhatsAppChannel(
        tenant_id=context.tenant_id,
        name=payload.name,
        phone_number=payload.phone_number,
        provider=payload.provider,
        provider_config=payload.provider_config,
        status=ChannelStatus.DISCONNECTED,
    )
    db.add(channel)
    db.commit()
    db.refresh(channel)
    return channel


@router.get("/{channel_id}/status", response_model=ChannelStatusResult)
async def channel_status(
    channel_id: UUID,
    context: AuthContext = Depends(get_auth_context),
    db: Session = Depends(get_db),
) -> ChannelStatusResult:
    channel = get_tenant_channel(db, context.tenant_id, channel_id)
    try:
        result = await get_provider(channel.provider).get_status(channel)
    except NotImplementedError as exc:
        raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail=str(exc)) from exc
    channel.status = result.status
    db.commit()
    return result


@router.get("/{channel_id}/qr", response_model=QRCodeResult)
async def channel_qr(
    channel_id: UUID,
    context: AuthContext = Depends(get_auth_context),
    db: Session = Depends(get_db),
) -> QRCodeResult:
    channel = get_tenant_channel(db, context.tenant_id, channel_id)
    try:
        result = await get_provider(channel.provider).get_qr_code(channel)
    except NotImplementedError as exc:
        raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail=str(exc)) from exc
    channel.status = result.status
    db.commit()
    return result
