from typing import Any

from app.channels.models import WhatsAppChannel
from app.providers.base import (
    ChannelStatusResult,
    IncomingMessageResult,
    QRCodeResult,
    SendResult,
    WhatsAppProvider,
)


class BspProvider(WhatsAppProvider):
    async def send_text(
        self,
        channel: WhatsAppChannel,
        to: str,
        text: str,
        *,
        reply_to_provider_message_id: str | None = None,
        reply_to_participant: str | None = None,
        mentioned_phones: list[str] | None = None,
        idempotency_key: str | None = None,
    ) -> SendResult:
        raise NotImplementedError("BSP ainda não foi selecionado")

    async def send_media(
        self,
        channel: WhatsAppChannel,
        to: str,
        file_url: str,
        caption: str | None = None,
        *,
        reply_to_provider_message_id: str | None = None,
        reply_to_participant: str | None = None,
        mentioned_phones: list[str] | None = None,
        idempotency_key: str | None = None,
    ) -> SendResult:
        raise NotImplementedError("BSP ainda não foi selecionado")

    async def get_status(self, channel: WhatsAppChannel) -> ChannelStatusResult:
        raise NotImplementedError("BSP ainda não foi selecionado")

    async def get_qr_code(self, channel: WhatsAppChannel) -> QRCodeResult:
        raise NotImplementedError("O fluxo depende do BSP selecionado")

    async def handle_webhook(self, payload: dict[str, Any]) -> IncomingMessageResult:
        raise NotImplementedError("BSP ainda não foi selecionado")
