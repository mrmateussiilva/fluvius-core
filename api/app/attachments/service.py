import base64
import binascii
import mimetypes
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from uuid import UUID

from sqlalchemy.orm import Session

from app.attachments.models import MessageAttachment
from app.common.enums import MessageType
from app.messages.models import Message
from app.providers.base import IncomingMessageResult
from app.storage.local import LocalStorageProvider


MAX_MEDIA_BYTES = 25 * 1024 * 1024

DOCUMENT_CONTENT_TYPES = {
    ".csv": "text/csv",
    ".doc": "application/msword",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".pdf": "application/pdf",
    ".ppt": "application/vnd.ms-powerpoint",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".txt": "text/plain",
    ".xls": "application/vnd.ms-excel",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".zip": "application/zip",
}


class UnsupportedAttachmentError(ValueError):
    pass


@dataclass(frozen=True)
class ValidatedAttachment:
    message_type: MessageType
    content_type: str
    content_sha256: str


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


def validate_outgoing_attachment(
    content_type: str,
    file_name: str,
    content: bytes,
) -> ValidatedAttachment:
    """Validate the file bytes instead of trusting browser-provided metadata."""
    extension = Path(file_name).suffix.lower()
    normalized_declared = content_type.split(";", 1)[0].strip().lower()
    detected = _detect_content_type(
        content,
        extension=extension,
        declared_content_type=normalized_declared,
    )
    if detected is None:
        raise UnsupportedAttachmentError(
            "Formato não suportado. Envie imagem, áudio, vídeo, PDF, Office, texto ou ZIP."
        )

    detected_type = message_type_for_upload(detected, file_name)
    extension_type = _message_type_for_extension(extension)
    if extension_type is None:
        raise UnsupportedAttachmentError("A extensão do arquivo não é suportada")
    if extension_type != detected_type:
        raise UnsupportedAttachmentError(
            "O conteúdo do arquivo não corresponde à extensão informada"
        )

    if normalized_declared not in {"", "application/octet-stream"}:
        declared_type = message_type_for_upload(normalized_declared, file_name)
        if declared_type != detected_type:
            raise UnsupportedAttachmentError(
                "O conteúdo do arquivo não corresponde ao tipo informado pelo navegador"
            )

    return ValidatedAttachment(
        message_type=detected_type,
        content_type=detected,
        content_sha256=sha256(content).hexdigest(),
    )


def _message_type_for_extension(extension: str) -> MessageType | None:
    if extension == ".webp":
        return MessageType.STICKER
    if extension in {".gif", ".jpeg", ".jpg", ".png"}:
        return MessageType.IMAGE
    if extension in {".aac", ".flac", ".m4a", ".mp3", ".oga", ".ogg", ".wav", ".weba"}:
        return MessageType.AUDIO
    if extension in {".m4v", ".mov", ".mp4", ".webm"}:
        return MessageType.VIDEO
    if extension in DOCUMENT_CONTENT_TYPES:
        return MessageType.DOCUMENT
    return None


def _detect_content_type(
    content: bytes,
    *,
    extension: str,
    declared_content_type: str,
) -> str | None:
    if content.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if content.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if content.startswith(b"RIFF") and content[8:12] == b"WEBP":
        return "image/webp"
    if content.startswith(b"%PDF-"):
        return "application/pdf"
    if content.startswith(b"OggS"):
        return "audio/ogg"
    if content.startswith(b"fLaC"):
        return "audio/flac"
    if content.startswith(b"RIFF") and content[8:12] == b"WAVE":
        return "audio/wav"
    if len(content) >= 2 and content[0] == 0xFF and content[1] & 0xF6 == 0xF0:
        return "audio/aac"
    if content.startswith(b"ID3") or (
        len(content) >= 2 and content[0] == 0xFF and content[1] & 0xE0 == 0xE0
    ):
        return "audio/mpeg"
    if len(content) >= 12 and content[4:8] == b"ftyp":
        if extension == ".m4a" or declared_content_type.startswith("audio/"):
            return "audio/mp4"
        if extension == ".mov":
            return "video/quicktime"
        return "video/mp4"
    if content.startswith(b"\x1aE\xdf\xa3"):
        if extension == ".weba" or declared_content_type.startswith("audio/"):
            return "audio/webm"
        return "video/webm"
    if content.startswith(b"PK\x03\x04") and extension in DOCUMENT_CONTENT_TYPES:
        return DOCUMENT_CONTENT_TYPES[extension]
    if content.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1") and extension in {
        ".doc",
        ".ppt",
        ".xls",
    }:
        return DOCUMENT_CONTENT_TYPES[extension]
    if extension in {".csv", ".txt"} and b"\x00" not in content:
        try:
            content.decode("utf-8")
        except UnicodeDecodeError:
            return None
        return DOCUMENT_CONTENT_TYPES[extension]
    return None


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

    declared_content_type = (
        incoming.media_content_type or _default_content_type(incoming.message_type)
    ).split(";", 1)[0]
    file_name = incoming.media_file_name or _default_file_name(
        incoming.provider_message_id,
        incoming.message_type,
        declared_content_type,
    )
    try:
        validated = validate_outgoing_attachment(
            declared_content_type,
            file_name,
            content,
        )
    except UnsupportedAttachmentError:
        return None, "Formato de mídia recebido não é suportado ou está inconsistente"
    if validated.message_type != incoming.message_type:
        return None, "Tipo da mídia recebida não corresponde ao conteúdo"
    try:
        stored = await LocalStorageProvider().save(str(tenant_id), file_name, content)
    except OSError:
        return None, "Não foi possível armazenar a mídia recebida"
    attachment = MessageAttachment(
        tenant_id=tenant_id,
        message_id=message.id,
        file_name=file_name,
        content_type=validated.content_type,
        size_bytes=stored.size_bytes,
        content_sha256=validated.content_sha256,
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
