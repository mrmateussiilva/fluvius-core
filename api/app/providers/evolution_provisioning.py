from secrets import token_urlsafe
from uuid import UUID

from sqlalchemy.orm import Session

from app.channels.models import WhatsAppChannel
from app.common.audit_models import AuditLog
from app.common.enums import ChannelStatus
from app.providers.evolution_admin import (
    EvolutionGoAdminClient,
    EvolutionGoProvisioningError,
    EvolutionInstance,
)
from app.providers.evolution_credentials import (
    ProviderConfigurationError,
    decrypt_provider_secret,
    get_channel_credential,
    store_channel_credential,
)
from app.providers.evolution_go import EvolutionGoProvider


def prepare_managed_evolution_channel(
    db: Session,
    channel: WhatsAppChannel,
) -> None:
    EvolutionGoAdminClient().ensure_configured()
    instance_name = f"fluvius-{channel.id.hex}"
    channel.provider_config = {
        "instance_name": instance_name,
        "managed": True,
    }
    store_channel_credential(db, channel, token_urlsafe(32))


async def provision_evolution_channel(
    db: Session,
    channel: WhatsAppChannel,
    *,
    actor_user_id: UUID,
) -> None:
    credential = get_channel_credential(db, channel, for_update=True)
    if credential is None:
        # Legacy channels are already provisioned outside Fluvius.
        return
    if credential.provisioning_status == "active":
        return

    token = decrypt_provider_secret(credential.encrypted_secret)
    instance_name = str(channel.provider_config.get("instance_name") or "")
    if not instance_name:
        raise ProviderConfigurationError(
            "O identificador da instância gerenciada não está disponível"
        )

    credential.provisioning_status = "pending"
    credential.last_error = None
    channel.status = ChannelStatus.CONNECTING
    db.commit()

    instance = EvolutionInstance(
        instance_id=str(channel.id),
        name=instance_name,
        token=token,
    )
    error: EvolutionGoProvisioningError | None = None
    try:
        await EvolutionGoAdminClient().create_instance(instance)
    except EvolutionGoProvisioningError as exc:
        error = exc

    if error is not None and error.ambiguous:
        confirmation = await EvolutionGoProvider(api_key=token).get_status(channel)
        if confirmation.error is None:
            error = None

    credential = get_channel_credential(db, channel, for_update=True)
    if credential is None:
        raise ProviderConfigurationError(
            "A credencial protegida do canal não está mais disponível"
        )
    if error is None:
        credential.provisioning_status = "active"
        credential.last_error = None
        channel.status = ChannelStatus.DISCONNECTED
        db.add(
            AuditLog(
                tenant_id=channel.tenant_id,
                user_id=actor_user_id,
                action="channel.provisioned",
                entity_type="whatsapp_channel",
                entity_id=channel.id,
                metadata_={"provider": "evolution_go"},
            )
        )
        db.commit()
        return

    credential.provisioning_status = (
        "uncertain" if error.ambiguous else "failed"
    )
    credential.last_error = str(error)
    channel.status = ChannelStatus.FAILED
    db.add(
        AuditLog(
            tenant_id=channel.tenant_id,
            user_id=actor_user_id,
            action="channel.provision_failed",
            entity_type="whatsapp_channel",
            entity_id=channel.id,
            metadata_={
                "provider": "evolution_go",
                "ambiguous": error.ambiguous,
            },
        )
    )
    db.commit()
    raise error
