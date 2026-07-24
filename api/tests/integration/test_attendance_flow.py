from unittest.mock import patch

from sqlalchemy import func, select

from app.channels.models import WhatsAppChannel
from app.common.enums import ChannelStatus, MessageStatus
from app.config import settings
from app.contacts.models import Contact
from app.conversations.models import Conversation
from app.database import SessionLocal
from app.messages.models import Message
from app.providers.base import SendResult
from .base import PostgresIntegrationTestCase


class ConfirmingProvider:
    def __init__(self, provider_message_id: str) -> None:
        self.provider_message_id = provider_message_id
        self.calls: list[dict] = []

    async def send_text(self, channel, to: str, text: str, **kwargs) -> SendResult:
        self.calls.append(
            {
                "channel_id": channel.id,
                "to": to,
                "text": text,
                "idempotency_key": kwargs.get("idempotency_key"),
            }
        )
        return SendResult(
            success=True,
            provider_message_id=self.provider_message_id,
            status=MessageStatus.SENT,
        )


class AttendanceFlowTest(PostgresIntegrationTestCase):
    customer_phone = "5527993333333"

    def incoming_payload(self, message_id: str, body: str) -> dict:
        return {
            "event": "Message",
            "instanceId": "integration-instance",
            "instanceName": "tenant-a",
            "instanceToken": settings.evolution_go_api_key,
            "data": {
                "Info": {
                    "ID": message_id,
                    "Sender": f"{self.customer_phone}@s.whatsapp.net",
                    "Chat": f"{self.customer_phone}@s.whatsapp.net",
                    "IsFromMe": False,
                    "IsGroup": False,
                    "PushName": "Cliente Integração",
                    "Timestamp": "2026-07-24T10:00:00-03:00",
                    "Type": "text",
                },
                "Message": {"conversation": body},
            },
        }

    @staticmethod
    def receipt_payload(provider_message_id: str, state: str) -> dict:
        return {
            "event": "Receipt",
            "state": state,
            "instanceToken": settings.evolution_go_api_key,
            "data": {
                "MessageIDs": [provider_message_id],
                "Timestamp": "2026-07-24T10:05:00-03:00",
                "Type": state.lower(),
            },
        }

    def test_complete_attendance_lifecycle_is_idempotent_and_traceable(self) -> None:
        webhook_url = (
            "/api/v1/webhooks/whatsapp/evolution_go/"
            f"{self.tenant_a.channel_id}"
        )
        first_payload = self.incoming_payload("incoming-integration-1", "Olá")
        first_payload["tenant_id"] = str(self.tenant_b.tenant_id)

        incoming = self.client.post(webhook_url, json=first_payload)
        self.assertEqual(incoming.status_code, 202, incoming.text)
        self.assertEqual(incoming.json()["status"], "accepted")

        conversations = self.client.get(
            "/api/v1/conversations", headers=self.headers_a
        )
        self.assertEqual(conversations.status_code, 200)
        created = next(
            conversation
            for conversation in conversations.json()
            if conversation["contact_phone"] == self.customer_phone
        )
        conversation_id = created["id"]
        self.assertEqual(created["status"], "new")
        self.assertEqual(created["unread_count"], 1)

        assigned = self.client.post(
            f"/api/v1/conversations/{conversation_id}/assign",
            headers=self.headers_a,
            json={},
        )
        self.assertEqual(assigned.status_code, 200, assigned.text)
        self.assertEqual(assigned.json()["status"], "open")
        self.assertEqual(
            assigned.json()["assigned_user_id"],
            str(self.tenant_a.user_id),
        )

        with SessionLocal() as db:
            channel = db.scalar(
                select(WhatsAppChannel).where(
                    WhatsAppChannel.id == self.tenant_a.channel_id,
                    WhatsAppChannel.tenant_id == self.tenant_a.tenant_id,
                )
            )
            channel.status = ChannelStatus.DISCONNECTED
            message_count_before = db.scalar(
                select(func.count(Message.id)).where(
                    Message.tenant_id == self.tenant_a.tenant_id,
                    Message.conversation_id == conversation_id,
                )
            )
            db.commit()

        blocked = self.client.post(
            f"/api/v1/conversations/{conversation_id}/messages",
            headers=self.headers_a,
            json={"text": "Não deve sair"},
        )
        self.assertEqual(blocked.status_code, 409)

        with SessionLocal() as db:
            message_count_after = db.scalar(
                select(func.count(Message.id)).where(
                    Message.tenant_id == self.tenant_a.tenant_id,
                    Message.conversation_id == conversation_id,
                )
            )
            channel = db.scalar(
                select(WhatsAppChannel).where(
                    WhatsAppChannel.id == self.tenant_a.channel_id,
                    WhatsAppChannel.tenant_id == self.tenant_a.tenant_id,
                )
            )
            channel.status = ChannelStatus.CONNECTED
            db.commit()
        self.assertEqual(message_count_after, message_count_before)

        provider = ConfirmingProvider("outgoing-integration-1")
        with patch("app.messages.router.get_provider", return_value=provider):
            outgoing = self.client.post(
                f"/api/v1/conversations/{conversation_id}/messages",
                headers=self.headers_a,
                json={"text": "Olá! Como posso ajudar?"},
            )

        self.assertEqual(outgoing.status_code, 201, outgoing.text)
        outgoing_message = outgoing.json()
        self.assertEqual(outgoing_message["status"], "sent")
        self.assertEqual(
            outgoing_message["provider_message_id"],
            "outgoing-integration-1",
        )
        self.assertEqual(len(provider.calls), 1)
        self.assertEqual(
            provider.calls[0]["idempotency_key"],
            outgoing_message["id"],
        )

        delivered = self.client.post(
            webhook_url,
            json=self.receipt_payload("outgoing-integration-1", "Delivered"),
        )
        self.assertEqual(delivered.status_code, 202, delivered.text)
        read = self.client.post(
            webhook_url,
            json=self.receipt_payload("outgoing-integration-1", "Read"),
        )
        self.assertEqual(read.status_code, 202, read.text)

        messages = self.client.get(
            f"/api/v1/conversations/{conversation_id}/messages",
            headers=self.headers_a,
        )
        confirmed = next(
            message
            for message in messages.json()
            if message["id"] == outgoing_message["id"]
        )
        self.assertEqual(confirmed["status"], "read")
        self.assertIsNotNone(confirmed["delivered_at"])
        self.assertIsNotNone(confirmed["read_at"])

        closed = self.client.post(
            f"/api/v1/conversations/{conversation_id}/close",
            headers=self.headers_a,
        )
        self.assertEqual(closed.status_code, 200)
        self.assertEqual(closed.json()["status"], "closed")

        second_payload = self.incoming_payload(
            "incoming-integration-2",
            "Ainda preciso de ajuda",
        )
        reopened = self.client.post(webhook_url, json=second_payload)
        self.assertEqual(reopened.status_code, 202, reopened.text)

        current = self.client.get(
            f"/api/v1/conversations/{conversation_id}",
            headers=self.headers_a,
        )
        self.assertEqual(current.status_code, 200)
        self.assertEqual(current.json()["status"], "new")
        self.assertIsNone(current.json()["assigned_user_id"])

        duplicate = self.client.post(webhook_url, json=second_payload)
        self.assertEqual(duplicate.status_code, 202)
        self.assertEqual(duplicate.json()["status"], "duplicate")

        with SessionLocal() as db:
            contact = db.scalar(
                select(Contact).where(
                    Contact.tenant_id == self.tenant_a.tenant_id,
                    Contact.phone_number == self.customer_phone,
                )
            )
            conversation_count = db.scalar(
                select(func.count(Conversation.id)).where(
                    Conversation.tenant_id == self.tenant_a.tenant_id,
                    Conversation.channel_id == self.tenant_a.channel_id,
                    Conversation.contact_id == contact.id,
                )
            )
            incoming_count = db.scalar(
                select(func.count(Message.id)).where(
                    Message.tenant_id == self.tenant_a.tenant_id,
                    Message.conversation_id == conversation_id,
                    Message.provider_message_id.in_(
                        ["incoming-integration-1", "incoming-integration-2"]
                    ),
                )
            )

        self.assertEqual(conversation_count, 1)
        self.assertEqual(incoming_count, 2)
