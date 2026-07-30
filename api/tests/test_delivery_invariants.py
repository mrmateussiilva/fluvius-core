import unittest
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

from app.common.enums import MessageStatus
from app.conversations.router import conversation_query
from app.delivery.dispatcher import _claim_dispatcher_lock, _release_dispatcher_lock
from app.messages.router import apply_send_result, format_outgoing_content
from app.providers.base import SendResult
from redis.exceptions import RedisError


class DeliveryInvariantTest(unittest.TestCase):
    def test_formats_outgoing_text_with_the_sender_snapshot(self) -> None:
        self.assertEqual(
            format_outgoing_content(
                "  Mateus   Vendedor  ",
                "Me manda uma mensagem caso tenha dúvida?",
            ),
            "*Mateus Vendedor:*\nMe manda uma mensagem caso tenha dúvida?",
        )
        self.assertEqual(
            format_outgoing_content(None, "Mensagem sem identificação"),
            "Mensagem sem identificação",
        )
        self.assertIsNone(format_outgoing_content("Mateus", None))

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


class DeliveryDispatcherLockTest(unittest.TestCase):
    def test_claim_uses_redis_nx_lock(self) -> None:
        with patch("app.delivery.dispatcher.redis_connection") as redis:
            redis.set.return_value = True
            self.assertTrue(_claim_dispatcher_lock())
            redis.set.assert_called_once()
            kwargs = redis.set.call_args.kwargs
            self.assertTrue(kwargs.get("nx"))
            self.assertEqual(kwargs.get("ex"), 8)

    def test_claim_fails_closed_on_redis_errors(self) -> None:
        with patch("app.delivery.dispatcher.redis_connection") as redis:
            redis.set.side_effect = RedisError("down")
            self.assertFalse(_claim_dispatcher_lock())
            redis.delete.side_effect = RedisError("down")
            _release_dispatcher_lock()


if __name__ == "__main__":
    unittest.main()
