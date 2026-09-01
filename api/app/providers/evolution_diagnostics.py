from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter

from app.channels.models import WhatsAppChannel
from app.common.enums import ChannelStatus
from app.providers.evolution_contract import (
    EVOLUTION_GO_IMAGE_VERSION,
    EVOLUTION_GO_SOURCE_REF,
    EVOLUTION_GO_VERSION,
)
from app.providers.evolution_go import EvolutionGoProvider


@dataclass(frozen=True, slots=True)
class EvolutionChannelProbe:
    status: ChannelStatus
    raw_status: str | None
    latency_ms: int
    error: str | None
    contract_version: str = EVOLUTION_GO_VERSION
    image_version: str = EVOLUTION_GO_IMAGE_VERSION
    source_ref: str = EVOLUTION_GO_SOURCE_REF


async def probe_evolution_channel(
    provider: EvolutionGoProvider,
    channel: WhatsAppChannel,
) -> EvolutionChannelProbe:
    started_at = perf_counter()
    result = await provider.get_status(channel)
    latency_ms = max(0, round((perf_counter() - started_at) * 1000))
    return EvolutionChannelProbe(
        status=result.status,
        raw_status=result.raw_status,
        latency_ms=latency_ms,
        error=result.error,
    )
