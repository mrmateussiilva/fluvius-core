from dataclasses import dataclass

import httpx

from app.config import settings
from app.providers.evolution_credentials import ProviderConfigurationError


class EvolutionGoProvisioningError(RuntimeError):
    """A safe provisioning error that never includes credentials or raw payloads."""

    def __init__(self, message: str, *, ambiguous: bool = False) -> None:
        super().__init__(message)
        self.ambiguous = ambiguous


@dataclass(frozen=True)
class EvolutionInstance:
    instance_id: str
    name: str
    token: str


class EvolutionGoAdminClient:
    def __init__(
        self,
        *,
        base_url: str | None = None,
        global_api_key: str | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.base_url = (base_url or settings.evolution_go_base_url).rstrip("/")
        self.global_api_key = (
            global_api_key
            if global_api_key is not None
            else settings.evolution_go_global_api_key
        )
        self.transport = transport

    def ensure_configured(self) -> None:
        if not self.global_api_key:
            raise ProviderConfigurationError(
                "A credencial administrativa da Evolution Go não está configurada"
            )

    @property
    def headers(self) -> dict[str, str]:
        self.ensure_configured()
        # Never log this dictionary: it contains the infrastructure credential.
        return {"apikey": self.global_api_key, "Content-Type": "application/json"}

    async def create_instance(self, instance: EvolutionInstance) -> None:
        try:
            async with httpx.AsyncClient(
                base_url=self.base_url,
                timeout=httpx.Timeout(20.0),
                transport=self.transport,
            ) as client:
                response = await client.post(
                    "/instance/create",
                    headers=self.headers,
                    json={
                        "instanceId": instance.instance_id,
                        "name": instance.name,
                        "token": instance.token,
                    },
                )
            if response.is_success:
                return
            if response.status_code == 409:
                raise EvolutionGoProvisioningError(
                    "A instância já existe; confirmando a associação.",
                    ambiguous=True,
                )
            if response.status_code in {401, 403}:
                raise EvolutionGoProvisioningError(
                    "A Evolution Go recusou a credencial administrativa."
                )
            if response.status_code == 503:
                raise EvolutionGoProvisioningError(
                    "A Evolution Go ainda não está ativada ou está indisponível."
                )
            raise EvolutionGoProvisioningError(
                f"A Evolution Go recusou a criação da instância (HTTP {response.status_code})."
            )
        except EvolutionGoProvisioningError:
            raise
        except (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError) as exc:
            raise EvolutionGoProvisioningError(
                "A confirmação da criação não chegou; o estado será verificado novamente.",
                ambiguous=True,
            ) from exc
