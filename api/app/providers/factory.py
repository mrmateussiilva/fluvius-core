from app.common.enums import ChannelProvider
from app.providers.base import WhatsAppProvider
from app.providers.bsp import BspProvider
from app.providers.evolution_go import EvolutionGoProvider
from app.providers.meta_cloud import MetaCloudProvider


def get_provider(provider: ChannelProvider | str) -> WhatsAppProvider:
    provider = ChannelProvider(provider)
    providers: dict[ChannelProvider, type[WhatsAppProvider]] = {
        ChannelProvider.EVOLUTION_GO: EvolutionGoProvider,
        ChannelProvider.META_CLOUD: MetaCloudProvider,
        ChannelProvider.BSP: BspProvider,
    }
    return providers[provider]()
