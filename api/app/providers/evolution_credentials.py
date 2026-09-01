import base64
from hashlib import sha256

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.channels.models import WhatsAppChannel
from app.common.enums import ChannelProvider
from app.config import settings
from app.providers.models import ProviderCredential


class ProviderConfigurationError(ValueError):
    """A safe provider configuration error that can be returned by the API."""


def normalize_evolution_config(provider_config: dict) -> dict[str, str]:
    instance_name = provider_config.get("instance_name")
    if not isinstance(instance_name, str) or not instance_name.strip():
        raise ProviderConfigurationError("Informe a instância Evolution configurada")
    return {"instance_name": instance_name.strip()}


def secret_fingerprint(secret: str) -> str:
    return sha256(secret.encode()).hexdigest()


def _credential_cipher() -> Fernet:
    # A dedicated deploy-level key is preferred. Falling back to SECRET_KEY keeps
    # existing installations operational without introducing per-channel env vars.
    master_key = settings.provider_credentials_key or settings.secret_key
    if not master_key:
        raise ProviderConfigurationError("A chave de proteção das credenciais não está configurada")
    derived_key = sha256(f"fluvius-provider-credentials:v1:{master_key}".encode()).digest()
    return Fernet(base64.urlsafe_b64encode(derived_key))


def encrypt_provider_secret(secret: str) -> bytes:
    if not secret:
        raise ProviderConfigurationError("A credencial do provider está vazia")
    return _credential_cipher().encrypt(secret.encode())


def decrypt_provider_secret(encrypted_secret: bytes) -> str:
    try:
        return _credential_cipher().decrypt(encrypted_secret).decode()
    except (InvalidToken, UnicodeDecodeError) as exc:
        raise ProviderConfigurationError(
            "Não foi possível abrir a credencial protegida deste canal"
        ) from exc


def get_channel_credential(
    db: Session,
    channel: WhatsAppChannel,
    *,
    for_update: bool = False,
) -> ProviderCredential | None:
    query = select(ProviderCredential).where(
        ProviderCredential.tenant_id == channel.tenant_id,
        ProviderCredential.channel_id == channel.id,
        ProviderCredential.provider == str(channel.provider),
    )
    if for_update:
        query = query.with_for_update()
    return db.scalar(query)


def store_channel_credential(
    db: Session,
    channel: WhatsAppChannel,
    secret: str,
    *,
    provisioning_status: str = "pending",
) -> ProviderCredential:
    fingerprint = secret_fingerprint(secret)
    credential = ProviderCredential(
        tenant_id=channel.tenant_id,
        channel_id=channel.id,
        provider=str(channel.provider),
        encrypted_secret=encrypt_provider_secret(secret),
        secret_fingerprint=fingerprint,
        provisioning_status=provisioning_status,
    )
    channel.credential_fingerprint = fingerprint
    db.add(credential)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise ProviderConfigurationError(
            "Esta credencial Evolution já está associada a outro canal"
        ) from exc
    return credential


def legacy_evolution_api_key(provider_config: dict) -> str:
    instance_name = normalize_evolution_config(provider_config)["instance_name"]
    configured_tokens = settings.evolution_go_instance_tokens
    if configured_tokens:
        token = configured_tokens.get(instance_name, "")
        if not token:
            raise ProviderConfigurationError(
                "A instância Evolution informada não está configurada na API"
            )
        return token
    if not settings.evolution_go_api_key:
        raise ProviderConfigurationError("A credencial da Evolution não está configurada na API")
    return settings.evolution_go_api_key


def evolution_api_key(
    provider_config: dict,
    *,
    db: Session | None = None,
    channel: WhatsAppChannel | None = None,
) -> str:
    if db is not None and channel is not None:
        credential = ensure_evolution_channel_credential(db, channel)
        if credential is not None:
            return decrypt_provider_secret(credential.encrypted_secret)
    return legacy_evolution_api_key(provider_config)


def evolution_credential_fingerprint(
    provider_config: dict,
    *,
    db: Session | None = None,
    channel: WhatsAppChannel | None = None,
) -> str:
    return secret_fingerprint(evolution_api_key(provider_config, db=db, channel=channel))


def claim_evolution_credential(
    db: Session,
    channel: WhatsAppChannel,
) -> None:
    if channel.provider != ChannelProvider.EVOLUTION_GO:
        return
    credential = get_channel_credential(db, channel)
    fingerprint = (
        credential.secret_fingerprint
        if credential is not None
        else evolution_credential_fingerprint(
            channel.provider_config,
        )
    )
    if channel.credential_fingerprint == fingerprint:
        return
    channel.credential_fingerprint = fingerprint
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise ProviderConfigurationError(
            "Esta instância Evolution já está associada a outro canal"
        ) from exc


def ensure_evolution_channel_credential(
    db: Session,
    channel: WhatsAppChannel,
) -> ProviderCredential | None:
    if channel.provider != ChannelProvider.EVOLUTION_GO:
        return None
    credential = get_channel_credential(db, channel, for_update=True)
    if credential is not None:
        return credential
    legacy_secret = legacy_evolution_api_key(channel.provider_config)
    return store_channel_credential(
        db,
        channel,
        legacy_secret,
        provisioning_status="active",
    )
