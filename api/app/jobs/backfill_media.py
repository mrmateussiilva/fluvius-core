import asyncio

from sqlalchemy import select

from app.attachments.models import MessageAttachment
from app.attachments.service import persist_incoming_attachment
from app.database import SessionLocal, load_all_models
from app.messages.models import Message
from app.providers.factory import get_provider
from app.providers.models import ProviderEvent


async def backfill_media() -> None:
    load_all_models()
    restored = 0
    failed = 0
    with SessionLocal() as db:
        events = list(
            db.scalars(
                select(ProviderEvent)
                .where(ProviderEvent.event_type == "Message")
                .order_by(ProviderEvent.created_at)
            )
        )
        for event in events:
            data = event.payload.get("data", {})
            provider_message = data.get("Message", data.get("message", {}))
            if not isinstance(provider_message, dict) or not provider_message.get("base64"):
                continue
            message = db.scalar(
                select(Message).where(
                    Message.tenant_id == event.tenant_id,
                    Message.provider_message_id == event.provider_event_id,
                )
            )
            if message is None:
                continue
            existing = db.scalar(
                select(MessageAttachment).where(
                    MessageAttachment.tenant_id == event.tenant_id,
                    MessageAttachment.message_id == message.id,
                )
            )
            if existing:
                continue
            provider = get_provider(event.provider)
            try:
                incoming = await provider.handle_webhook(event.payload)
                attachment, error = await persist_incoming_attachment(
                    db,
                    tenant_id=event.tenant_id,
                    message=message,
                    incoming=incoming,
                )
            except ValueError:
                attachment, error = None, "Evento de mídia antigo inválido"
            if attachment:
                event.payload = provider.sanitize_webhook_payload(event.payload)
                message.message_type = incoming.message_type
                if incoming.body and not message.body:
                    message.body = incoming.body
                message.error = None
                restored += 1
            elif error:
                message.error = error
                failed += 1
        db.commit()
    print(f"Backfill de mídia concluído: restaurados={restored} falhas={failed}")


if __name__ == "__main__":
    asyncio.run(backfill_media())
