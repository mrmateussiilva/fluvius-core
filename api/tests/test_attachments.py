import asyncio
import base64
import unittest
from datetime import UTC, datetime
from hashlib import sha256
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from app.attachments.service import (
    UnsupportedAttachmentError,
    message_type_for_upload,
    persist_incoming_attachment,
    validate_outgoing_attachment,
)
from app.common.enums import MessageType
from app.providers.base import IncomingMessageResult
from app.storage.base import StoredFile


class FakeSession:
    def __init__(self) -> None:
        self.added = []

    def add(self, value) -> None:
        self.added.append(value)


class AttachmentTest(unittest.TestCase):
    def test_classifies_supported_uploads(self) -> None:
        self.assertEqual(message_type_for_upload("image/jpeg", "foto.jpg"), MessageType.IMAGE)
        self.assertEqual(message_type_for_upload("audio/ogg", "voz.ogg"), MessageType.AUDIO)
        self.assertEqual(message_type_for_upload("video/mp4", "video.mp4"), MessageType.VIDEO)
        self.assertEqual(message_type_for_upload("image/webp", "sticker.webp"), MessageType.STICKER)
        self.assertEqual(
            message_type_for_upload("application/pdf", "arquivo.pdf"),
            MessageType.DOCUMENT,
        )

    def test_validates_file_signature_and_integrity_hash(self) -> None:
        content = b"\x89PNG\r\n\x1a\nvalid-image"
        validated = validate_outgoing_attachment(
            "image/png",
            "foto.png",
            content,
        )

        self.assertEqual(validated.message_type, MessageType.IMAGE)
        self.assertEqual(validated.content_type, "image/png")
        self.assertEqual(validated.content_sha256, sha256(content).hexdigest())

    def test_validates_each_supported_media_category(self) -> None:
        cases = (
            ("foto.jpg", "image/jpeg", b"\xff\xd8\xffimage", MessageType.IMAGE),
            ("voz.mp3", "audio/mpeg", b"ID3audio", MessageType.AUDIO),
            (
                "video.mp4",
                "video/mp4",
                b"\x00\x00\x00\x18ftypisomvideo",
                MessageType.VIDEO,
            ),
            ("arquivo.pdf", "application/pdf", b"%PDF-1.7 document", MessageType.DOCUMENT),
            (
                "planilha.xlsx",
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                b"PK\x03\x04spreadsheet",
                MessageType.DOCUMENT,
            ),
        )
        for file_name, content_type, content, expected in cases:
            with self.subTest(file_name=file_name):
                validated = validate_outgoing_attachment(
                    content_type,
                    file_name,
                    content,
                )
                self.assertEqual(validated.message_type, expected)

    def test_validates_structured_text_documents(self) -> None:
        cases = (
            ("pagina.html", "text/html", b"<!doctype html><html><body>OK</body></html>"),
            ("pagina.htm", "text/html", b"<html><body>OK</body></html>"),
            ("dados.json", "application/json", b'{"status":"ok"}'),
            ("dados.xml", "application/xml", b"<?xml version='1.0'?><status>ok</status>"),
        )
        for file_name, content_type, content in cases:
            with self.subTest(file_name=file_name):
                validated = validate_outgoing_attachment(
                    content_type,
                    file_name,
                    content,
                )
                self.assertEqual(validated.message_type, MessageType.DOCUMENT)
                self.assertEqual(validated.content_type, content_type)

    def test_rejects_invalid_or_unsafe_structured_documents(self) -> None:
        cases = (
            ("pagina.html", "text/html", b"plain text without html structure"),
            ("dados.json", "application/json", b"{invalid}"),
            ("dados.json", "application/json", b"PK\x03\x04disguised zip"),
            ("dados.xml", "application/xml", b"<!DOCTYPE data><data>unsafe</data>"),
            ("dados.xml", "application/xml", b"<data>broken"),
        )
        for file_name, content_type, content in cases:
            with self.subTest(file_name=file_name):
                with self.assertRaises(UnsupportedAttachmentError):
                    validate_outgoing_attachment(content_type, file_name, content)

    def test_rejects_a_file_disguised_with_another_extension(self) -> None:
        with self.assertRaisesRegex(
            UnsupportedAttachmentError,
            "não corresponde à extensão",
        ):
            validate_outgoing_attachment(
                "image/jpeg",
                "foto.jpg",
                b"%PDF-1.7 disguised",
            )

    def test_rejects_an_unknown_binary_format(self) -> None:
        with self.assertRaisesRegex(UnsupportedAttachmentError, "Formato não suportado"):
            validate_outgoing_attachment(
                "application/octet-stream",
                "arquivo.bin",
                b"\x00\x01\x02\x03",
            )

    def test_persists_incoming_base64_media(self) -> None:
        tenant_id = uuid4()
        message = SimpleNamespace(id=uuid4())
        content = b"\x89PNG\r\n\x1a\nincoming-image"
        incoming = IncomingMessageResult(
            provider_message_id="MEDIA-123",
            from_number="5527999999999",
            to_number="instance",
            message_type=MessageType.IMAGE,
            media_base64=base64.b64encode(content).decode(),
            media_content_type="image/png",
            media_file_name="imagem.png",
            timestamp=datetime.now(UTC),
            raw_payload={},
        )
        db = FakeSession()
        with patch(
            "app.attachments.service.LocalStorageProvider.save",
            new=AsyncMock(
                return_value=StoredFile(
                    key="tenant/image.jpg",
                    public_url="http://localhost:8000/storage/tenant/image.jpg",
                    size_bytes=len(content),
                )
            ),
        ):
            attachment, error = asyncio.run(
                persist_incoming_attachment(
                    db,
                    tenant_id=tenant_id,
                    message=message,
                    incoming=incoming,
                )
            )
        self.assertIsNone(error)
        self.assertIsNotNone(attachment)
        self.assertEqual(attachment.content_type, "image/png")
        self.assertEqual(attachment.size_bytes, len(content))
        self.assertEqual(attachment.content_sha256, sha256(content).hexdigest())
        self.assertEqual(db.added, [attachment])

    def test_persists_incoming_base64_document(self) -> None:
        tenant_id = uuid4()
        message = SimpleNamespace(id=uuid4())
        content = b"%PDF-1.7\ndocumento recebido"
        incoming = IncomingMessageResult(
            provider_message_id="DOCUMENT-123",
            from_number="5527999999999",
            to_number="instance",
            message_type=MessageType.DOCUMENT,
            media_base64=base64.b64encode(content).decode(),
            media_content_type="application/pdf",
            media_file_name="contrato.pdf",
            timestamp=datetime.now(UTC),
            raw_payload={},
        )
        db = FakeSession()
        with patch(
            "app.attachments.service.LocalStorageProvider.save",
            new=AsyncMock(
                return_value=StoredFile(
                    key="tenant/contrato.pdf",
                    public_url="http://localhost:8000/storage/tenant/contrato.pdf",
                    size_bytes=len(content),
                )
            ),
        ):
            attachment, error = asyncio.run(
                persist_incoming_attachment(
                    db,
                    tenant_id=tenant_id,
                    message=message,
                    incoming=incoming,
                )
            )

        self.assertIsNone(error)
        self.assertIsNotNone(attachment)
        self.assertEqual(attachment.file_name, "contrato.pdf")
        self.assertEqual(attachment.content_type, "application/pdf")
        self.assertEqual(attachment.size_bytes, len(content))
        self.assertEqual(attachment.content_sha256, sha256(content).hexdigest())
        self.assertEqual(db.added, [attachment])


if __name__ == "__main__":
    unittest.main()
