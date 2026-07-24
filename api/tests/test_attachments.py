import asyncio
import unittest
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from app.attachments.service import (
    message_type_for_upload,
    persist_incoming_attachment,
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

    def test_persists_incoming_base64_media(self) -> None:
        tenant_id = uuid4()
        message = SimpleNamespace(id=uuid4())
        incoming = IncomingMessageResult(
            provider_message_id="MEDIA-123",
            from_number="5527999999999",
            to_number="instance",
            message_type=MessageType.IMAGE,
            media_base64="aW1hZ2Vt",
            media_content_type="image/jpeg",
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
                    size_bytes=6,
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
        self.assertEqual(attachment.content_type, "image/jpeg")
        self.assertEqual(attachment.size_bytes, 6)
        self.assertEqual(db.added, [attachment])


if __name__ == "__main__":
    unittest.main()
