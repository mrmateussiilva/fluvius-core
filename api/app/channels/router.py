from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth.dependencies import AuthContext, get_auth_context
from app.channels.models import WhatsAppChannel
from app.channels.schemas import ChannelCreate, ChannelResponse
from app.common.enums import ChannelProvider, ChannelStatus
from app.database import get_db
from app.providers.base import ChannelStatusResult, QRCodeResult
from app.providers.evolution_credentials import (
    ProviderConfigurationError,
    claim_evolution_credential,
    evolution_credential_fingerprint,
)
from app.providers.factory import get_provider
from app.realtime.manager import realtime_manager

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
    if payload.provider == ChannelProvider.EVOLUTION_GO:
        try:
            channel.credential_fingerprint = evolution_credential_fingerprint(
                payload.provider_config
            )
        except ProviderConfigurationError as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    db.add(channel)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Esta instância Evolution já está associada a outro canal",
        ) from exc
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
        if channel.provider == ChannelProvider.EVOLUTION_GO:
            claim_evolution_credential(db, channel)
        result = await get_provider(channel.provider, channel).get_status(channel)
    except ProviderConfigurationError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except NotImplementedError as exc:
        raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail=str(exc)) from exc
    previous_status = channel.status
    channel.status = result.status
    db.commit()
    if previous_status != channel.status:
        await realtime_manager.broadcast(
            channel.tenant_id,
            "channel.status.updated",
            {"id": str(channel.id), "status": channel.status.value},
        )
    return result


async def connect_tenant_channel(
    channel_id: UUID,
    context: AuthContext,
    db: Session,
) -> QRCodeResult:
    channel = get_tenant_channel(db, context.tenant_id, channel_id)
    try:
        if channel.provider == ChannelProvider.EVOLUTION_GO:
            claim_evolution_credential(db, channel)
        result = await get_provider(channel.provider, channel).get_qr_code(channel)
    except ProviderConfigurationError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except NotImplementedError as exc:
        raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail=str(exc)) from exc
    previous_status = channel.status
    channel.status = result.status
    db.commit()
    if previous_status != channel.status:
        await realtime_manager.broadcast(
            channel.tenant_id,
            "channel.status.updated",
            {"id": str(channel.id), "status": channel.status.value},
        )
    return result


@router.post("/{channel_id}/connect", response_model=QRCodeResult)
async def connect_channel(
    channel_id: UUID,
    context: AuthContext = Depends(get_auth_context),
    db: Session = Depends(get_db),
) -> QRCodeResult:
    return await connect_tenant_channel(channel_id, context, db)


@router.get("/{channel_id}/qr", response_model=QRCodeResult)
async def channel_qr(
    channel_id: UUID,
    context: AuthContext = Depends(get_auth_context),
    db: Session = Depends(get_db),
) -> QRCodeResult:
    """Backward-compatible QR route; new clients should use POST /connect."""
    return await connect_tenant_channel(channel_id, context, db)
