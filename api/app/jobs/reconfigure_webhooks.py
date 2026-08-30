"""Reapply the active public webhook URL to every Evolution Go channel."""

import asyncio
import sys

from sqlalchemy import select

from app.channels.models import WhatsAppChannel
from app.common.enums import ChannelProvider
from app.database import SessionLocal, load_all_models
from app.providers.evolution_http import close_evolution_http_clients
from app.providers.factory import get_provider


async def reconfigure_webhooks() -> int:
    load_all_models()
    db = SessionLocal()
    failures: list[str] = []
    try:
        channels = list(
            db.scalars(
                select(WhatsAppChannel)
                .where(WhatsAppChannel.provider == ChannelProvider.EVOLUTION_GO)
                .order_by(WhatsAppChannel.created_at)
            )
        )
        for channel in channels:
            try:
                provider = get_provider(channel.provider, channel, db)
                await provider._configure_webhook(channel)  # noqa: SLF001
            except Exception as exc:  # noqa: BLE001
                failures.append(f"{channel.id} ({type(exc).__name__})")
        if failures:
            print(
                "Falha ao reconfigurar webhooks dos canais: " + ", ".join(failures),
                file=sys.stderr,
            )
            return 1
        print(f"Webhooks reconfigurados: {len(channels)} canal(is).")
        return 0
    finally:
        db.close()
        await close_evolution_http_clients()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(reconfigure_webhooks()))
