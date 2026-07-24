import base64
import binascii
import mimetypes
from uuid import UUID

from sqlalchemy.orm import Session

from app.attachments.models import MessageAttachment
from app.common.enums import MessageType
from app.messages.models import Message
from app.providers.base import IncomingMessageResult
from app.storage.local import LocalStorageProvider


MAX_MEDIA_BYTES = 25 * 1024 * 1024


def message_type_for_upload(content_type: str, file_name: str) -> MessageType:
    normalized = content_type.split(";", 1)[0].strip().lower()
    if normalized == "image/webp" or file_name.lower().endswith(".webp"):
        return MessageType.STICKER
    if normalized.startswith("image/"):
        return MessageType.IMAGE
    if normalized.startswith("audio/"):
        return MessageType.AUDIO
    if normalized.startswith("video/"):
        return MessageType.VIDEO
    return MessageType.DOCUMENT


async def persist_incoming_attachment(
    db: Session,
    *,
    tenant_id: UUID,
    message: Message,
    incoming: IncomingMessageResult,
) -> tuple[MessageAttachment | None, str | None]:
    if incoming.message_type == MessageType.TEXT or not incoming.media_base64:
        return None, None
    encoded = incoming.media_base64
    if encoded.startswith("data:") and "," in encoded:
        encoded = encoded.split(",", 1)[1]
    estimated_size = len(encoded) * 3 // 4
    if estimated_size > MAX_MEDIA_BYTES:
        return None, "Mídia recebida excede o limite de 25 MB"
    try:
        content = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError):
        return None, "Mídia recebida possui base64 inválido"
    if not content:
        return None, "Mídia recebida está vazia"
    if len(content) > MAX_MEDIA_BYTES:
        return None, "Mídia recebida excede o limite de 25 MB"

    content_type = (
        incoming.media_content_type or _default_content_type(incoming.message_type)
    ).split(";", 1)[0]
    file_name = incoming.media_file_name or _default_file_name(
        incoming.provider_message_id,
        incoming.message_type,
        content_type,
    )
    try:
        stored = await LocalStorageProvider().save(str(tenant_id), file_name, content)
    except OSError:
        return None, "Não foi possível armazenar a mídia recebida"
    attachment = MessageAttachment(
        tenant_id=tenant_id,
        message_id=message.id,
        file_name=file_name,
        content_type=content_type,
        size_bytes=stored.size_bytes,
        storage_key=stored.key,
        public_url=stored.public_url,
    )
    db.add(attachment)
    return attachment, None


def _default_content_type(message_type: MessageType) -> str:
    return {
        MessageType.IMAGE: "image/jpeg",
        MessageType.AUDIO: "audio/ogg",
        MessageType.VIDEO: "video/mp4",
        MessageType.STICKER: "image/webp",
        MessageType.DOCUMENT: "application/octet-stream",
    }.get(message_type, "application/octet-stream")


def _default_file_name(
    provider_message_id: str,
    message_type: MessageType,
    content_type: str,
) -> str:
    extension = mimetypes.guess_extension(content_type) or {
        MessageType.IMAGE: ".jpg",
        MessageType.AUDIO: ".ogg",
        MessageType.VIDEO: ".mp4",
        MessageType.STICKER: ".webp",
        MessageType.DOCUMENT: ".bin",
    }.get(message_type, ".bin")
    if extension == ".jpe":
        extension = ".jpg"
    return f"whatsapp-{provider_message_id}{extension}"
