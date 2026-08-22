import unittest
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

from app.channels.models import WhatsAppChannel
from app.common.enums import (
    ChannelProvider,
    ChannelStatus,
    ContactKind,
    MessageDirection,
    MessageStatus,
)
from app.contacts.models import Contact
from app.delivery.service import (
    apply_send_result,
    delivery_target,
    format_outgoing_content,
    normalized_sender_name,
    quote_participant,
)
from app.messages.models import Message
from app.providers.base import SendResult


class MessagePipelineUnitTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tenant_id = uuid4()
        self.channel_id = uuid4()
        self.conversation_id = uuid4()
        self.contact_id = uuid4()

    def test_normalized_sender_name_handles_edge_cases(self) -> None:
        self.assertIsNone(normalized_sender_name(None))
        self.assertIsNone(normalized_sender_name(""))
        self.assertIsNone(normalized_sender_name("   \t\n  "))
        self.assertEqual(normalized_sender_name("  João   Silva  "), "João Silva")
        self.assertEqual(normalized_sender_name("Alice"), "Alice")

    def test_format_outgoing_content_formatting(self) -> None:
        self.assertIsNone(format_outgoing_content("Agente", None))
        self.assertIsNone(format_outgoing_content(None, None))
        self.assertEqual(
            format_outgoing_content(None, "Mensagem direta"),
            "Mensagem direta",
        )
        self.assertEqual(
            format_outgoing_content("   ", "Mensagem direta"),
            "Mensagem direta",
        )
        self.assertEqual(
            format_outgoing_content("Carlos Atendente", "Olá!"),
            "*Carlos Atendente:*\nOlá!",
        )

    def test_delivery_target_resolution(self) -> None:
        contact_with_provider_address = Contact(
            id=self.contact_id,
            tenant_id=self.tenant_id,
            kind=ContactKind.DIRECT,
            phone_number="5511999998888",
            provider_address="5511999998888@s.whatsapp.net",
        )
        self.assertEqual(
            delivery_target(contact_with_provider_address),
            "5511999998888@s.whatsapp.net",
        )

        contact_direct_fallback = Contact(
            id=uuid4(),
            tenant_id=self.tenant_id,
            kind=ContactKind.DIRECT,
            phone_number="5511999998888",
            provider_address=None,
        )
        self.assertEqual(
            delivery_target(contact_direct_fallback),
            "5511999998888",
        )

        contact_group_fallback = Contact(
            id=uuid4(),
            tenant_id=self.tenant_id,
            kind=ContactKind.GROUP,
            phone_number="120363000000000000",
            provider_address=None,
        )
        self.assertEqual(
            delivery_target(contact_group_fallback),
            "120363000000000000@g.us",
        )

    def test_quote_participant_incoming_and_outgoing(self) -> None:
        channel = WhatsAppChannel(
            id=self.channel_id,
            tenant_id=self.tenant_id,
            phone_number="5511977776666",
            provider=ChannelProvider.EVOLUTION_GO,
            status=ChannelStatus.CONNECTED,
        )
        contact_individual = Contact(
            id=self.contact_id,
            tenant_id=self.tenant_id,
            kind=ContactKind.DIRECT,
            phone_number="5511999998888",
            provider_address="5511999998888@s.whatsapp.net",
        )
        contact_group = Contact(
            id=uuid4(),
            tenant_id=self.tenant_id,
            kind=ContactKind.GROUP,
            phone_number="120363000000000000",
            provider_address="120363000000000000@g.us",
        )

        # 1. Incoming direct message: quotes sender contact phone
        incoming_msg = Message(
            id=uuid4(),
            tenant_id=self.tenant_id,
            direction=MessageDirection.INCOMING,
            participant_phone=None,
        )
        self.assertEqual(
            quote_participant(channel=channel, contact=contact_individual, reply_to=incoming_msg),
            "5511999998888",
        )

        # 2. Incoming group message with participant_phone: quotes participant
        incoming_group_msg = Message(
            id=uuid4(),
            tenant_id=self.tenant_id,
            direction=MessageDirection.INCOMING,
            participant_phone="5511911112222",
        )
        self.assertEqual(
            quote_participant(channel=channel, contact=contact_group, reply_to=incoming_group_msg),
            "5511911112222",
        )

        # 3. Incoming group message without participant_phone: returns None
        incoming_group_no_part = Message(
            id=uuid4(),
            tenant_id=self.tenant_id,
            direction=MessageDirection.INCOMING,
            participant_phone=None,
        )
        self.assertIsNone(
            quote_participant(
                channel=channel,
                contact=contact_group,
                reply_to=incoming_group_no_part,
            )
        )

        # 4. Outgoing message in direct chat: quotes channel phone
        outgoing_msg = Message(
            id=uuid4(),
            tenant_id=self.tenant_id,
            direction=MessageDirection.OUTGOING,
        )
        self.assertEqual(
            quote_participant(channel=channel, contact=contact_individual, reply_to=outgoing_msg),
            "5511977776666",
        )

    def test_apply_send_result_invariants(self) -> None:
        # Success with valid provider id
        msg1 = SimpleNamespace(
            status=MessageStatus.PENDING,
            provider_message_id=None,
            error="old error",
            sent_at=None,
        )
        now = datetime.now(UTC)
        apply_send_result(
            msg1,
            SendResult(success=True, provider_message_id="PROV-999"),
            confirmed_at=now,
        )
        self.assertEqual(msg1.status, MessageStatus.SENT)
        self.assertEqual(msg1.provider_message_id, "PROV-999")
        self.assertIsNone(msg1.error)
        self.assertEqual(msg1.sent_at, now)

        # Success with empty string provider id is marked as failure
        msg2 = SimpleNamespace(
            status=MessageStatus.PENDING,
            provider_message_id=None,
            error=None,
            sent_at=None,
        )
        apply_send_result(msg2, SendResult(success=True, provider_message_id=""))
        self.assertEqual(msg2.status, MessageStatus.FAILED)
        self.assertIsNone(msg2.provider_message_id)
        self.assertIn("identificador", msg2.error)
        self.assertIsNone(msg2.sent_at)

        # Explicit failure preserves custom error
        msg3 = SimpleNamespace(
            status=MessageStatus.PENDING,
            provider_message_id=None,
            error=None,
            sent_at=None,
        )
        apply_send_result(
            msg3,
            SendResult(success=False, error="Instância desconectada"),
        )
        self.assertEqual(msg3.status, MessageStatus.FAILED)
        self.assertEqual(msg3.error, "Instância desconectada")
        self.assertIsNone(msg3.sent_at)


if __name__ == "__main__":
    unittest.main()
