import unittest
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from app.attachments.models import MessageAttachment
from app.auth.dependencies import AuthContext
from app.common.enums import (
    MessageDirection,
    MessageStatus,
    MessageType,
)
from app.messages.models import Message
from app.messages.router import message_list_response
from app.users.models import TenantUser, User


class MockDB:
    """Lightweight in-memory DB double for testing query construction and response serialization."""

    def __init__(self, objects: list | None = None) -> None:
        self.objects = objects or []

    def scalars(self, statement):
        results = []
        for obj in self.objects:
            results.append(obj)
        return results

    def scalar(self, statement):
        if self.objects:
            return self.objects[0]
        return None


def make_test_message(
    *,
    tenant_id,
    conversation_id,
    direction=MessageDirection.INCOMING,
    message_type=MessageType.TEXT,
    body="Texto",
    status=MessageStatus.READ,
    reply_to_message_id=None,
    created_at=None,
) -> Message:
    return Message(
        id=uuid4(),
        tenant_id=tenant_id,
        conversation_id=conversation_id,
        direction=direction,
        message_type=message_type,
        body=body,
        status=status,
        reply_to_message_id=reply_to_message_id,
        mentioned_phones=[],
        mentioned_jids=[],
        referenced_contacts=[],
        attempt_count=0,
        edit_content_unavailable=False,
        created_at=created_at or datetime.now(UTC),
    )


class MessagePaginationUnitTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tenant_id = uuid4()
        self.user_id = uuid4()
        self.channel_id = uuid4()
        self.conversation_id = uuid4()
        self.contact_id = uuid4()

        self.user = User(
            id=self.user_id,
            email="agent@fluvius.com",
            name="Agent One",
            password_hash="hash",
            is_active=True,
        )
        self.membership = TenantUser(
            tenant_id=self.tenant_id,
            user_id=self.user_id,
        )
        self.auth_context = AuthContext(
            user=self.user,
            membership=self.membership,
        )

    def test_message_list_response_aggregates_replies_and_attachments(self) -> None:
        msg_parent = make_test_message(
            tenant_id=self.tenant_id,
            conversation_id=self.conversation_id,
            direction=MessageDirection.INCOMING,
            message_type=MessageType.TEXT,
            body="Mensagem pai",
            status=MessageStatus.READ,
            created_at=datetime.now(UTC) - timedelta(minutes=5),
        )
        msg_child = make_test_message(
            tenant_id=self.tenant_id,
            conversation_id=self.conversation_id,
            reply_to_message_id=msg_parent.id,
            direction=MessageDirection.OUTGOING,
            message_type=MessageType.IMAGE,
            body="Com anexo",
            status=MessageStatus.SENT,
            created_at=datetime.now(UTC),
        )
        attachment = MessageAttachment(
            id=uuid4(),
            tenant_id=self.tenant_id,
            message_id=msg_child.id,
            file_name="foto.jpg",
            content_type="image/jpeg",
            size_bytes=1024,
            storage_key="tenants/1/foto.jpg",
            public_url="http://api/attachments/1",
        )

        class CustomMockDB:
            def scalars(self, stmt):
                stmt_str = str(stmt)
                if "attachments" in stmt_str:
                    return [attachment]
                if "message_contact_shares" in stmt_str:
                    return []
                if "reply_to_message_id" in stmt_str or "messages" in stmt_str:
                    return [msg_parent]
                return []

            def scalar(self, stmt):
                return None

        responses = message_list_response(
            CustomMockDB(),
            self.tenant_id,
            [msg_child],
        )

        self.assertEqual(len(responses), 1)
        self.assertEqual(responses[0].id, msg_child.id)
        self.assertIsNotNone(responses[0].reply_to)
        self.assertEqual(responses[0].reply_to.id, msg_parent.id)
        self.assertEqual(responses[0].reply_to.body, "Mensagem pai")
        self.assertEqual(len(responses[0].attachments), 1)
        self.assertEqual(responses[0].attachments[0].file_name, "foto.jpg")

    def test_message_list_response_empty(self) -> None:
        responses = message_list_response(
            MockDB([]),
            self.tenant_id,
            [],
        )
        self.assertEqual(responses, [])


if __name__ == "__main__":
    unittest.main()
