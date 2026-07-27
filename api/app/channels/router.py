from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth.dependencies import AuthContext, get_auth_context
from app.channels.models import WhatsAppChannel
from app.channels.schemas import ChannelCreate, ChannelResponse
from app.common.audit_models import AuditLog
from app.common.enums import ChannelProvider, ChannelStatus
from app.database import get_db
from app.providers.base import ChannelStatusResult, QRCodeResult
from app.providers.evolution_admin import EvolutionGoProvisioningError
from app.providers.evolution_credentials import (
    ProviderConfigurationError,
    claim_evolution_credential,
    evolution_credential_fingerprint,
)
from app.providers.evolution_provisioning import (
    prepare_managed_evolution_channel,
    provision_evolution_channel,
)
from app.providers.factory import get_provider
from app.realtime.manager import realtime_manager
from app.users.router import require_admin
from app.users.channel_access import accessible_channel_ids, ensure_channel_access

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
    allowed_channel_ids = accessible_channel_ids(db, context)
    query = select(WhatsAppChannel).where(
        WhatsAppChannel.tenant_id == context.tenant_id
    )
    if allowed_channel_ids is not None:
        query = query.where(WhatsAppChannel.id.in_(allowed_channel_ids))
    return list(
        db.scalars(
            query.order_by(WhatsAppChannel.created_at)
        )
    )


@router.post("", response_model=ChannelResponse, status_code=status.HTTP_201_CREATED)
async def create_channel(
    payload: ChannelCreate,
    response: Response,
    context: AuthContext = Depends(require_admin),
    db: Session = Depends(get_db),
) -> WhatsAppChannel:
    if payload.provisioning_key is not None:
        existing_provision = db.scalar(
            select(WhatsAppChannel).where(
                WhatsAppChannel.tenant_id == context.tenant_id,
                WhatsAppChannel.provisioning_key == payload.provisioning_key,
            )
        )
        if existing_provision is not None:
            if existing_provision.provider == ChannelProvider.EVOLUTION_GO:
                try:
                    await provision_evolution_channel(
                        db,
                        existing_provision,
                        actor_user_id=context.user.id,
                    )
                except (ProviderConfigurationError, EvolutionGoProvisioningError) as exc:
                    raise HTTPException(
                        status_code=status.HTTP_502_BAD_GATEWAY,
                        detail=str(exc),
                    ) from exc
            response.status_code = status.HTTP_200_OK
            return existing_provision

    credential_fingerprint: str | None = None
    is_managed_evolution = (
        payload.provider == ChannelProvider.EVOLUTION_GO
        and not payload.provider_config
    )
    if payload.provider == ChannelProvider.EVOLUTION_GO and not is_managed_evolution:
        try:
            credential_fingerprint = evolution_credential_fingerprint(
                payload.provider_config
            )
        except ProviderConfigurationError as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
        existing_channel = db.scalar(
            select(WhatsAppChannel).where(
                WhatsAppChannel.tenant_id == context.tenant_id,
                WhatsAppChannel.provider == payload.provider,
                WhatsAppChannel.credential_fingerprint == credential_fingerprint,
            )
        )
        if existing_channel is not None:
            response.status_code = status.HTTP_200_OK
            return existing_channel

    channel = WhatsAppChannel(
        tenant_id=context.tenant_id,
        name=payload.name,
        phone_number=payload.phone_number,
        provider=payload.provider,
        provider_config=payload.provider_config,
        status=(
            ChannelStatus.CONNECTING
            if is_managed_evolution
            else ChannelStatus.DISCONNECTED
        ),
        credential_fingerprint=credential_fingerprint,
        provisioning_key=payload.provisioning_key,
    )
    db.add(channel)
    try:
        db.flush()
        if is_managed_evolution:
            prepare_managed_evolution_channel(db, channel)
        db.add(
            AuditLog(
                tenant_id=context.tenant_id,
                user_id=context.user.id,
                action="channel.created",
                entity_type="whatsapp_channel",
                entity_id=channel.id,
                metadata_={
                    "provider": payload.provider.value,
                    "managed": is_managed_evolution,
                },
            )
        )
        db.commit()
    except (IntegrityError, ProviderConfigurationError) as exc:
        db.rollback()
        if payload.provisioning_key is not None:
            existing_provision = db.scalar(
                select(WhatsAppChannel).where(
                    WhatsAppChannel.tenant_id == context.tenant_id,
                    WhatsAppChannel.provisioning_key == payload.provisioning_key,
                )
            )
            if existing_provision is not None:
                try:
                    await provision_evolution_channel(
                        db,
                        existing_provision,
                        actor_user_id=context.user.id,
                    )
                except (
                    ProviderConfigurationError,
                    EvolutionGoProvisioningError,
                ) as provisioning_exc:
                    raise HTTPException(
                        status_code=status.HTTP_502_BAD_GATEWAY,
                        detail=str(provisioning_exc),
                    ) from provisioning_exc
                response.status_code = status.HTTP_200_OK
                return existing_provision
        if credential_fingerprint is not None:
            existing_channel = db.scalar(
                select(WhatsAppChannel).where(
                    WhatsAppChannel.tenant_id == context.tenant_id,
                    WhatsAppChannel.provider == payload.provider,
                    WhatsAppChannel.credential_fingerprint == credential_fingerprint,
                )
            )
            if existing_channel is not None:
                response.status_code = status.HTTP_200_OK
                return existing_channel
        if credential_fingerprint is not None and isinstance(exc, IntegrityError):
            detail = "Esta credencial Evolution já está associada a outro canal"
        else:
            detail = (
                str(exc)
                if isinstance(exc, ProviderConfigurationError)
                else "Não foi possível reservar este canal"
            )
        error_status = (
            status.HTTP_503_SERVICE_UNAVAILABLE
            if is_managed_evolution and isinstance(exc, ProviderConfigurationError)
            else status.HTTP_409_CONFLICT
        )
        raise HTTPException(status_code=error_status, detail=detail) from exc
    db.refresh(channel)
    if is_managed_evolution:
        try:
            await provision_evolution_channel(
                db,
                channel,
                actor_user_id=context.user.id,
            )
        except (ProviderConfigurationError, EvolutionGoProvisioningError) as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=str(exc),
            ) from exc
    return channel


@router.get("/{channel_id}/status", response_model=ChannelStatusResult)
async def channel_status(
    channel_id: UUID,
    context: AuthContext = Depends(get_auth_context),
    db: Session = Depends(get_db),
) -> ChannelStatusResult:
    channel = get_tenant_channel(db, context.tenant_id, channel_id)
    ensure_channel_access(db, context, channel.id)
    try:
        if channel.provider == ChannelProvider.EVOLUTION_GO:
            claim_evolution_credential(db, channel)
        result = await get_provider(channel.provider, channel, db).get_status(channel)
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
            {
                "id": str(channel.id),
                "channel_id": str(channel.id),
                "status": channel.status.value,
            },
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
            await provision_evolution_channel(
                db,
                channel,
                actor_user_id=context.user.id,
            )
            claim_evolution_credential(db, channel)
        result = await get_provider(channel.provider, channel, db).get_qr_code(channel)
    except EvolutionGoProvisioningError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
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
            {
                "id": str(channel.id),
                "channel_id": str(channel.id),
                "status": channel.status.value,
            },
        )
    return result


@router.post("/{channel_id}/connect", response_model=QRCodeResult)
async def connect_channel(
    channel_id: UUID,
    context: AuthContext = Depends(require_admin),
    db: Session = Depends(get_db),
) -> QRCodeResult:
    return await connect_tenant_channel(channel_id, context, db)


@router.get("/{channel_id}/qr", response_model=QRCodeResult)
async def channel_qr(
    channel_id: UUID,
    context: AuthContext = Depends(require_admin),
    db: Session = Depends(get_db),
) -> QRCodeResult:
    """Backward-compatible QR route; new clients should use POST /connect."""
    return await connect_tenant_channel(channel_id, context, db)
