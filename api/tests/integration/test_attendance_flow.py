from hashlib import sha256
from unittest.mock import AsyncMock, patch
from uuid import UUID, uuid4

from sqlalchemy import func, select

from app.attachments.models import MessageAttachment
from app.channels.models import WhatsAppChannel
from app.common.enums import ChannelStatus, ContactKind, ConversationStatus, MessageStatus
from app.config import settings
from app.contacts.models import Contact
from app.conversations.models import Conversation
from app.database import SessionLocal
from app.delivery.models import MessageDelivery
from app.delivery.tasks import run_delivery
from app.messages.models import Message, MessageRevision
from app.providers.base import SendResult
from app.storage.base import StoredFile

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
                "mentioned_phones": kwargs.get("mentioned_phones"),
                "mentioned_jids": kwargs.get("mentioned_jids"),
            }
        )
        return SendResult(
            success=True,
            provider_message_id=self.provider_message_id,
            status=MessageStatus.SENT,
        )

    async def send_media(
        self,
        channel,
        to: str,
        file_url: str,
        caption: str | None = None,
        **kwargs,
    ) -> SendResult:
        self.calls.append(
            {
                "channel_id": channel.id,
                "to": to,
                "file_url": file_url,
                "caption": caption,
                "idempotency_key": kwargs.get("idempotency_key"),
                "mentioned_phones": kwargs.get("mentioned_phones"),
                "mentioned_jids": kwargs.get("mentioned_jids"),
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

    def edit_payload(
        self,
        event_id: str,
        target_message_id: str,
        body: str | None,
    ) -> dict:
        message = (
            {
                "protocolMessage": {
                    "key": {"ID": target_message_id},
                    "editedMessage": {
                        "extendedTextMessage": {"text": body}
                    },
                }
            }
            if body is not None
            else {
                "secretEncryptedMessage": {
                    "secretEncType": 2,
                    "targetMessageKey": {"ID": target_message_id},
                }
            }
        )
        payload = self.incoming_payload(event_id, "")
        payload["data"]["Info"]["Edit"] = "1"
        payload["data"]["Message"] = message
        return payload

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
        client_message_id = str(uuid4())
        with patch("app.delivery.service.get_provider", return_value=provider):
            outgoing = self.client.post(
                f"/api/v1/conversations/{conversation_id}/messages",
                headers=self.headers_a,
                json={
                    "text": "Olá! Como posso ajudar?",
                    "client_message_id": client_message_id,
                },
            )
            repeated = self.client.post(
                f"/api/v1/conversations/{conversation_id}/messages",
                headers=self.headers_a,
                json={
                    "text": "Olá! Como posso ajudar?",
                    "client_message_id": client_message_id,
                },
            )
            conflicting = self.client.post(
                f"/api/v1/conversations/{conversation_id}/messages",
                headers=self.headers_a,
                json={
                    "text": "Conteúdo diferente",
                    "client_message_id": client_message_id,
                },
            )
            with SessionLocal() as db:
                delivery = db.scalar(
                    select(MessageDelivery).where(
                        MessageDelivery.tenant_id == self.tenant_a.tenant_id,
                        MessageDelivery.message_id == UUID(client_message_id),
                    )
                )
                delivery_id = delivery.id
            run_delivery(str(delivery_id), str(self.tenant_a.tenant_id))

        self.assertEqual(outgoing.status_code, 202, outgoing.text)
        self.assertEqual(repeated.status_code, 202, repeated.text)
        self.assertEqual(conflicting.status_code, 409, conflicting.text)
        self.assertEqual(
            conflicting.json()["detail"],
            "Identificador de mensagem já utilizado",
        )
        outgoing_message = outgoing.json()
        self.assertEqual(outgoing_message["id"], client_message_id)
        self.assertEqual(repeated.json()["id"], client_message_id)
        self.assertEqual(outgoing_message["sender_name"], "Agente A")
        self.assertEqual(outgoing_message["status"], "pending")
        messages_after_delivery = self.client.get(
            f"/api/v1/conversations/{conversation_id}/messages",
            headers=self.headers_a,
        )
        outgoing_message = next(
            message
            for message in messages_after_delivery.json()
            if message["id"] == client_message_id
        )
        self.assertEqual(outgoing_message["status"], "sent")
        self.assertEqual(
            outgoing_message["provider_message_id"],
            "outgoing-integration-1",
        )
        self.assertEqual(len(provider.calls), 1)
        self.assertEqual(
            provider.calls[0]["text"],
            "*Agente A:*\nOlá! Como posso ajudar?",
        )
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

    def test_attachment_upload_is_validated_and_idempotent(self) -> None:
        assigned = self.client.post(
            f"/api/v1/conversations/{self.tenant_a.conversation_id}/assign",
            headers=self.headers_a,
            json={},
        )
        self.assertEqual(assigned.status_code, 200, assigned.text)

        provider = ConfirmingProvider("outgoing-media-1")
        client_message_id = str(uuid4())
        content = b"\x89PNG\r\n\x1a\nintegration-image"
        stored = StoredFile(
            key=f"{self.tenant_a.tenant_id}/image.png",
            public_url="http://api:8000/storage/tenant/image.png",
            size_bytes=len(content),
        )
        request = {
            "files": {"file": ("image.png", content, "image/png")},
            "data": {
                "caption": "Imagem validada",
                "client_message_id": client_message_id,
            },
        }
        with (
            patch("app.delivery.service.get_provider", return_value=provider),
            patch(
                "app.messages.router.LocalStorageProvider.save",
                new=AsyncMock(return_value=stored),
            ) as save,
        ):
            created = self.client.post(
                f"/api/v1/conversations/{self.tenant_a.conversation_id}/attachments",
                headers=self.headers_a,
                **request,
            )
            repeated = self.client.post(
                f"/api/v1/conversations/{self.tenant_a.conversation_id}/attachments",
                headers=self.headers_a,
                **request,
            )
            conflicting = self.client.post(
                f"/api/v1/conversations/{self.tenant_a.conversation_id}/attachments",
                headers=self.headers_a,
                files={
                    "file": (
                        "image.png",
                        b"\x89PNG\r\n\x1a\ndifferent-image",
                        "image/png",
                    )
                },
                data={
                    "caption": "Imagem validada",
                    "client_message_id": client_message_id,
                },
            )
            with SessionLocal() as db:
                delivery = db.scalar(
                    select(MessageDelivery).where(
                        MessageDelivery.tenant_id == self.tenant_a.tenant_id,
                        MessageDelivery.message_id == UUID(client_message_id),
                    )
                )
                delivery_id = delivery.id
            run_delivery(str(delivery_id), str(self.tenant_a.tenant_id))

        self.assertEqual(created.status_code, 202, created.text)
        self.assertEqual(repeated.status_code, 202, repeated.text)
        self.assertEqual(conflicting.status_code, 409, conflicting.text)
        self.assertEqual(created.json()["id"], client_message_id)
        self.assertEqual(created.json()["message_type"], "image")
        self.assertEqual(created.json()["sender_name"], "Agente A")
        self.assertEqual(created.json()["status"], "pending")
        self.assertEqual(repeated.json()["id"], client_message_id)
        self.assertEqual(len(provider.calls), 1)
        self.assertEqual(
            provider.calls[0]["caption"],
            "*Agente A:*\nImagem validada",
        )
        self.assertEqual(provider.calls[0]["idempotency_key"], client_message_id)
        self.assertEqual(save.await_count, 1)

        with SessionLocal() as db:
            attachment = db.scalar(
                select(MessageAttachment).where(
                    MessageAttachment.tenant_id == self.tenant_a.tenant_id,
                    MessageAttachment.message_id == UUID(client_message_id),
                )
            )
        self.assertIsNotNone(attachment)
        self.assertEqual(attachment.content_sha256, sha256(content).hexdigest())

        rejected = self.client.post(
            f"/api/v1/conversations/{self.tenant_a.conversation_id}/attachments",
            headers=self.headers_a,
            files={"file": ("fake.jpg", b"%PDF-1.7 fake image", "image/jpeg")},
            data={"client_message_id": str(uuid4())},
        )
        self.assertEqual(rejected.status_code, 415, rejected.text)

    def test_sticker_is_native_without_caption_and_idempotent(self) -> None:
        assigned = self.client.post(
            f"/api/v1/conversations/{self.tenant_a.conversation_id}/assign",
            headers=self.headers_a,
            json={},
        )
        self.assertEqual(assigned.status_code, 200, assigned.text)

        provider = ConfirmingProvider("outgoing-sticker-1")
        client_message_id = str(uuid4())
        content = b"RIFF\x0e\x00\x00\x00WEBPVP8 figurinha"
        stored = StoredFile(
            key=f"{self.tenant_a.tenant_id}/figurinha.webp",
            public_url="http://api:8000/storage/tenant/figurinha.webp",
            size_bytes=len(content),
        )
        request = {
            "files": {"file": ("figurinha.webp", content, "image/webp")},
            "data": {
                "caption": "Esta legenda não deve acompanhar a figurinha",
                "client_message_id": client_message_id,
            },
        }
        with (
            patch("app.delivery.service.get_provider", return_value=provider),
            patch(
                "app.messages.router.LocalStorageProvider.save",
                new=AsyncMock(return_value=stored),
            ) as save,
        ):
            created = self.client.post(
                f"/api/v1/conversations/{self.tenant_a.conversation_id}/attachments",
                headers=self.headers_a,
                **request,
            )
            repeated = self.client.post(
                f"/api/v1/conversations/{self.tenant_a.conversation_id}/attachments",
                headers=self.headers_a,
                **request,
            )
            with SessionLocal() as db:
                delivery = db.scalar(
                    select(MessageDelivery).where(
                        MessageDelivery.tenant_id == self.tenant_a.tenant_id,
                        MessageDelivery.message_id == UUID(client_message_id),
                    )
                )
                delivery_id = delivery.id
            run_delivery(str(delivery_id), str(self.tenant_a.tenant_id))

        self.assertEqual(created.status_code, 202, created.text)
        self.assertEqual(repeated.status_code, 202, repeated.text)
        self.assertEqual(created.json()["message_type"], "sticker")
        self.assertEqual(created.json()["sender_name"], "Agente A")
        self.assertIsNone(created.json()["body"])
        self.assertEqual(repeated.json()["id"], client_message_id)
        self.assertEqual(len(provider.calls), 1)
        self.assertIsNone(provider.calls[0]["caption"])
        self.assertEqual(provider.calls[0]["idempotency_key"], client_message_id)
        self.assertEqual(save.await_count, 1)

    def test_edits_update_the_original_message_and_reactions_are_ignored(self) -> None:
        webhook_url = (
            "/api/v1/webhooks/whatsapp/evolution_go/"
            f"{self.tenant_a.channel_id}"
        )
        original_id = "incoming-edit-original"
        created = self.client.post(
            webhook_url,
            json=self.incoming_payload(original_id, "Texto antes da edição"),
        )
        self.assertEqual(created.status_code, 202, created.text)

        edited = self.client.post(
            webhook_url,
            json=self.edit_payload(
                "incoming-edit-plaintext",
                original_id,
                "Texto depois da edição",
            ),
        )
        repeated = self.client.post(
            webhook_url,
            json=self.edit_payload(
                "incoming-edit-plaintext",
                original_id,
                "Texto depois da edição",
            ),
        )
        unavailable = self.client.post(
            webhook_url,
            json=self.edit_payload(
                "incoming-edit-encrypted",
                original_id,
                None,
            ),
        )
        reaction = self.incoming_payload("incoming-reaction-removed", "")
        reaction["data"]["Info"]["Edit"] = "7"
        reaction["data"]["Info"]["Type"] = "reaction"
        reaction["data"]["Message"] = {
            "reactionMessage": {
                "key": {"ID": original_id},
                "senderTimestampMS": 1785032722922,
            }
        }
        ignored = self.client.post(webhook_url, json=reaction)

        self.assertEqual(edited.status_code, 202, edited.text)
        self.assertEqual(edited.json()["status"], "accepted")
        self.assertEqual(repeated.json()["status"], "duplicate")
        self.assertEqual(unavailable.json()["status"], "accepted")
        self.assertEqual(ignored.json()["status"], "ignored")

        with SessionLocal() as db:
            message = db.scalar(
                select(Message).where(
                    Message.tenant_id == self.tenant_a.tenant_id,
                    Message.provider_message_id == original_id,
                )
            )
            message_count = db.scalar(
                select(func.count(Message.id)).where(
                    Message.tenant_id == self.tenant_a.tenant_id,
                    Message.provider_message_id.in_(
                        [
                            original_id,
                            "incoming-edit-plaintext",
                            "incoming-edit-encrypted",
                            "incoming-reaction-removed",
                        ]
                    ),
                )
            )
            revision_count = db.scalar(
                select(func.count(MessageRevision.id)).where(
                    MessageRevision.tenant_id == self.tenant_a.tenant_id,
                    MessageRevision.message_id == message.id,
                )
            )

        self.assertEqual(message.body, "Texto depois da edição")
        self.assertIsNotNone(message.edited_at)
        self.assertTrue(message.edit_content_unavailable)
        self.assertEqual(message_count, 1)
        self.assertEqual(revision_count, 2)

    def test_edit_is_reconciled_when_it_arrives_before_the_message(self) -> None:
        webhook_url = (
            "/api/v1/webhooks/whatsapp/evolution_go/"
            f"{self.tenant_a.channel_id}"
        )
        target_id = "incoming-after-edit"
        pending = self.client.post(
            webhook_url,
            json=self.edit_payload(
                "incoming-edit-before-original",
                target_id,
                "Texto já corrigido",
            ),
        )
        self.assertEqual(pending.status_code, 202, pending.text)
        self.assertEqual(pending.json()["status"], "pending")

        created = self.client.post(
            webhook_url,
            json=self.incoming_payload(target_id, "Texto original atrasado"),
        )
        self.assertEqual(created.status_code, 202, created.text)

        with SessionLocal() as db:
            message = db.scalar(
                select(Message).where(
                    Message.tenant_id == self.tenant_a.tenant_id,
                    Message.provider_message_id == target_id,
                )
            )

        self.assertEqual(message.body, "Texto já corrigido")
        self.assertIsNotNone(message.edited_at)
        self.assertFalse(message.edit_content_unavailable)

    def test_edit_target_cannot_cross_tenant_or_channel(self) -> None:
        webhook_url = (
            "/api/v1/webhooks/whatsapp/evolution_go/"
            f"{self.tenant_a.channel_id}"
        )
        pending = self.client.post(
            webhook_url,
            json=self.edit_payload(
                "incoming-cross-tenant-edit",
                "seed-b",
                "Tentativa cruzada",
            ),
        )
        self.assertEqual(pending.status_code, 202, pending.text)
        self.assertEqual(pending.json()["status"], "pending")

        with SessionLocal() as db:
            tenant_b_message = db.scalar(
                select(Message).where(
                    Message.tenant_id == self.tenant_b.tenant_id,
                    Message.provider_message_id == "seed-b",
                )
            )
            revision_count = db.scalar(
                select(func.count(MessageRevision.id)).where(
                    MessageRevision.tenant_id == self.tenant_b.tenant_id,
                    MessageRevision.message_id == tenant_b_message.id,
                )
            )

        self.assertEqual(tenant_b_message.body, "Mensagem do tenant B")
        self.assertIsNone(tenant_b_message.edited_at)
        self.assertEqual(revision_count, 0)

    def test_group_message_mentions_are_validated_and_delivered(self) -> None:
        with SessionLocal() as db:
            group = Contact(
                tenant_id=self.tenant_a.tenant_id,
                kind=ContactKind.GROUP,
                name="Grupo Operacional",
                phone_number="120363018686549942",
                provider_address="120363018686549942@g.us",
                group_members=[
                    {
                        "phone_number": "5527999999999",
                        "name": "Maria Operacao",
                        "is_admin": False,
                    },
                    {
                        "phone_number": "964169518424559641",
                        "provider_jid": "964169518424559641@lid",
                        "name": "Participante LID",
                        "is_admin": True,
                    }
                ],
            )
            db.add(group)
            db.flush()
            conversation = Conversation(
                tenant_id=self.tenant_a.tenant_id,
                channel_id=self.tenant_a.channel_id,
                contact_id=group.id,
                status=ConversationStatus.NEW,
            )
            db.add(conversation)
            db.commit()
            conversation_id = conversation.id

        assigned = self.client.post(
            f"/api/v1/conversations/{conversation_id}/assign",
            headers=self.headers_a,
            json={},
        )
        self.assertEqual(assigned.status_code, 200, assigned.text)

        unknown = self.client.post(
            f"/api/v1/conversations/{conversation_id}/messages",
            headers=self.headers_a,
            json={
                "text": "Oi @Pessoa",
                "mentioned_phones": ["5527888888888"],
            },
        )
        self.assertEqual(unknown.status_code, 422, unknown.text)

        unknown_lid = self.client.post(
            f"/api/v1/conversations/{conversation_id}/messages",
            headers=self.headers_a,
            json={
                "text": "Oi @Pessoa",
                "mentioned_jids": ["8833139028242378833@lid"],
            },
        )
        self.assertEqual(unknown_lid.status_code, 422, unknown_lid.text)

        provider = ConfirmingProvider("group-mention-1")
        client_message_id = str(uuid4())
        with patch("app.delivery.service.get_provider", return_value=provider):
            created = self.client.post(
                f"/api/v1/conversations/{conversation_id}/messages",
                headers=self.headers_a,
                json={
                    "text": "Oi @Maria Operacao e @Participante LID",
                    "mentioned_phones": ["+55 (27) 99999-9999"],
                    "mentioned_jids": ["964169518424559641@lid"],
                    "client_message_id": client_message_id,
                },
            )
            with SessionLocal() as db:
                delivery = db.scalar(
                    select(MessageDelivery).where(
                        MessageDelivery.tenant_id == self.tenant_a.tenant_id,
                        MessageDelivery.message_id == UUID(client_message_id),
                    )
                )
                delivery_id = delivery.id
            run_delivery(str(delivery_id), str(self.tenant_a.tenant_id))

        self.assertEqual(created.status_code, 202, created.text)
        self.assertEqual(created.json()["mentioned_phones"], ["5527999999999"])
        self.assertEqual(created.json()["mentioned_jids"], ["964169518424559641@lid"])
        self.assertEqual(provider.calls[0]["to"], "120363018686549942@g.us")
        self.assertEqual(provider.calls[0]["mentioned_phones"], ["5527999999999"])
        self.assertEqual(provider.calls[0]["mentioned_jids"], ["964169518424559641@lid"])

    def test_group_message_contact_references_are_internal_only(self) -> None:
        with SessionLocal() as db:
            group = Contact(
                tenant_id=self.tenant_a.tenant_id,
                kind=ContactKind.GROUP,
                name="Grupo Operacional",
                phone_number="120363018686549942",
                provider_address="120363018686549942@g.us",
                group_members=[
                    {
                        "phone_number": "5527999999999",
                        "name": "Maria Operacao",
                        "is_admin": False,
                    }
                ],
            )
            referenced = Contact(
                tenant_id=self.tenant_a.tenant_id,
                name="Joao Comercial",
                phone_number="5527993333333",
            )
            db.add_all([group, referenced])
            db.flush()
            conversation = Conversation(
                tenant_id=self.tenant_a.tenant_id,
                channel_id=self.tenant_a.channel_id,
                contact_id=group.id,
                status=ConversationStatus.NEW,
            )
            db.add(conversation)
            db.commit()
            conversation_id = conversation.id
            referenced_id = referenced.id

        assigned = self.client.post(
            f"/api/v1/conversations/{conversation_id}/assign",
            headers=self.headers_a,
            json={},
        )
        self.assertEqual(assigned.status_code, 200, assigned.text)

        search = self.client.get(
            "/api/v1/contacts/search?q=Joao",
            headers=self.headers_a,
        )
        self.assertEqual(search.status_code, 200, search.text)
        self.assertEqual(search.json()[0]["id"], str(referenced_id))

        cross_tenant = self.client.post(
            f"/api/v1/conversations/{conversation_id}/messages",
            headers=self.headers_a,
            json={
                "text": "Falar com @Contato B",
                "referenced_contact_ids": [str(self.tenant_b.contact_id)],
            },
        )
        self.assertEqual(cross_tenant.status_code, 422, cross_tenant.text)

        provider = ConfirmingProvider("group-reference-1")
        client_message_id = str(uuid4())
        with patch("app.delivery.service.get_provider", return_value=provider):
            created = self.client.post(
                f"/api/v1/conversations/{conversation_id}/messages",
                headers=self.headers_a,
                json={
                    "text": "Falar com @Joao Comercial",
                    "referenced_contact_ids": [str(referenced_id)],
                    "client_message_id": client_message_id,
                },
            )
            with SessionLocal() as db:
                delivery = db.scalar(
                    select(MessageDelivery).where(
                        MessageDelivery.tenant_id == self.tenant_a.tenant_id,
                        MessageDelivery.message_id == UUID(client_message_id),
                    )
                )
                delivery_id = delivery.id
            run_delivery(str(delivery_id), str(self.tenant_a.tenant_id))

        self.assertEqual(created.status_code, 202, created.text)
        self.assertEqual(created.json()["mentioned_phones"], [])
        self.assertEqual(
            created.json()["referenced_contacts"],
            [
                {
                    "contact_id": str(referenced_id),
                    "phone_number": "5527993333333",
                    "display_name": "Joao Comercial",
                }
            ],
        )
        self.assertEqual(provider.calls[0]["to"], "120363018686549942@g.us")
        self.assertEqual(provider.calls[0]["mentioned_phones"], [])
