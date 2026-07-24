from hashlib import sha256

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.channels.models import WhatsAppChannel
from app.config import settings


class ProviderConfigurationError(ValueError):
    """A safe provider configuration error that can be returned by the API."""


def normalize_evolution_config(provider_config: dict) -> dict[str, str]:
    instance_name = provider_config.get("instance_name")
    if not isinstance(instance_name, str) or not instance_name.strip():
        raise ProviderConfigurationError("Informe a instância Evolution configurada")
    return {"instance_name": instance_name.strip()}


def evolution_api_key(provider_config: dict) -> str:
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


def evolution_credential_fingerprint(provider_config: dict) -> str:
    return sha256(evolution_api_key(provider_config).encode()).hexdigest()


def claim_evolution_credential(
    db: Session,
    channel: WhatsAppChannel,
) -> None:
    fingerprint = evolution_credential_fingerprint(channel.provider_config)
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
