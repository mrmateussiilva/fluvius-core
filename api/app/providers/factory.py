from app.channels.models import WhatsAppChannel
from app.common.enums import ChannelProvider
from app.providers.base import WhatsAppProvider
from app.providers.bsp import BspProvider
from app.providers.evolution_credentials import evolution_api_key
from app.providers.evolution_go import EvolutionGoProvider
from app.providers.meta_cloud import MetaCloudProvider


def get_provider(
    provider: ChannelProvider | str,
    channel: WhatsAppChannel | None = None,
) -> WhatsAppProvider:
    provider = ChannelProvider(provider)
    if provider == ChannelProvider.EVOLUTION_GO and channel is not None:
        return EvolutionGoProvider(api_key=evolution_api_key(channel.provider_config))
    providers: dict[ChannelProvider, type[WhatsAppProvider]] = {
        ChannelProvider.EVOLUTION_GO: EvolutionGoProvider,
        ChannelProvider.META_CLOUD: MetaCloudProvider,
        ChannelProvider.BSP: BspProvider,
    }
    return providers[provider]()
