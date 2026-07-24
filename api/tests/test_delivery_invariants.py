import unittest
from types import SimpleNamespace
from uuid import uuid4

from app.common.enums import MessageStatus
from app.conversations.router import conversation_query
from app.messages.router import apply_send_result
from app.providers.base import SendResult


class DeliveryInvariantTest(unittest.TestCase):
    def test_positive_confirmation_with_provider_id_marks_message_as_sent(self) -> None:
        message = SimpleNamespace(
            status=MessageStatus.PENDING,
            provider_message_id=None,
            error="erro anterior",
            sent_at=None,
        )

        apply_send_result(
            message,
            SendResult(
                success=True,
                provider_message_id="PROVIDER-123",
                status=MessageStatus.READ,
            ),
        )

        self.assertEqual(message.status, MessageStatus.SENT)
        self.assertEqual(message.provider_message_id, "PROVIDER-123")
        self.assertIsNone(message.error)
        self.assertIsNotNone(message.sent_at)

    def test_success_without_provider_id_is_treated_as_failure(self) -> None:
        message = SimpleNamespace(
            status=MessageStatus.PENDING,
            provider_message_id=None,
            error=None,
            sent_at=None,
        )

        apply_send_result(message, SendResult(success=True))

        self.assertEqual(message.status, MessageStatus.FAILED)
        self.assertIsNone(message.provider_message_id)
        self.assertIn("identificador", message.error)
        self.assertIsNone(message.sent_at)

    def test_negative_confirmation_preserves_safe_provider_error(self) -> None:
        message = SimpleNamespace(
            status=MessageStatus.PENDING,
            provider_message_id=None,
            error=None,
            sent_at=None,
        )

        apply_send_result(
            message,
            SendResult(success=False, error="Gateway indisponível"),
        )

        self.assertEqual(message.status, MessageStatus.FAILED)
        self.assertEqual(message.error, "Gateway indisponível")


class ConversationTenantScopeTest(unittest.TestCase):
    def test_conversation_query_scopes_joined_operational_data(self) -> None:
        statement = str(conversation_query(uuid4(), uuid4()))

        self.assertIn("conversations.tenant_id", statement)
        self.assertIn("contacts.tenant_id", statement)
        self.assertIn("whatsapp_channels.tenant_id", statement)


if __name__ == "__main__":
    unittest.main()
