from urllib.parse import quote
from uuid import UUID

from sqlalchemy import select
from starlette.websockets import WebSocketDisconnect

from app.channels.models import WhatsAppChannel
from app.conversations.models import ConversationRead
from app.database import SessionLocal
from app.quick_replies.models import QuickReply
from app.security import create_access_token
from app.users.models import TenantUser, User
from .base import PostgresIntegrationTestCase, TEST_PASSWORD


class TenantIsolationTest(PostgresIntegrationTestCase):
    def test_lists_and_creates_resources_only_inside_authenticated_tenant(self) -> None:
        me = self.client.get("/api/v1/auth/me", headers=self.headers_a)
        self.assertEqual(me.status_code, 200)
        self.assertEqual(me.json()["tenant_id"], str(self.tenant_a.tenant_id))

        channels = self.client.get("/api/v1/channels", headers=self.headers_a)
        self.assertEqual(channels.status_code, 200)
        self.assertEqual(
            {channel["id"] for channel in channels.json()},
            {str(self.tenant_a.channel_id)},
        )

        conversations = self.client.get(
            "/api/v1/conversations", headers=self.headers_a
        )
        self.assertEqual(conversations.status_code, 200)
        self.assertEqual(
            {conversation["id"] for conversation in conversations.json()},
            {str(self.tenant_a.conversation_id)},
        )

        messages = self.client.get(
            f"/api/v1/conversations/{self.tenant_a.conversation_id}/messages",
            headers=self.headers_a,
        )
        self.assertEqual(messages.status_code, 200)
        self.assertEqual(
            {message["id"] for message in messages.json()},
            {str(self.tenant_a.message_id)},
        )

        quick_replies = self.client.get(
            "/api/v1/quick-replies", headers=self.headers_a
        )
        self.assertEqual(quick_replies.status_code, 200)
        self.assertEqual(
            {reply["id"] for reply in quick_replies.json()},
            {str(self.tenant_a.quick_reply_id)},
        )

        created_channel = self.client.post(
            "/api/v1/channels",
            headers=self.headers_a,
            json={
                "name": "Canal adicional A",
                "provider": "evolution_go",
                "provider_config": {"instance_name": "tenant-a-extra"},
            },
        )
        self.assertEqual(created_channel.status_code, 201, created_channel.text)

        created_reply = self.client.post(
            "/api/v1/quick-replies",
            headers=self.headers_a,
            json={
                "shortcut": "/novo",
                "title": "Nova resposta",
                "content": "Conteúdo isolado",
            },
        )
        self.assertEqual(created_reply.status_code, 201, created_reply.text)

        with SessionLocal() as db:
            channel = db.scalar(
                select(WhatsAppChannel).where(
                    WhatsAppChannel.id == UUID(created_channel.json()["id"]),
                    WhatsAppChannel.tenant_id == self.tenant_a.tenant_id,
                )
            )
            quick_reply = db.scalar(
                select(QuickReply).where(
                    QuickReply.id == UUID(created_reply.json()["id"]),
                    QuickReply.tenant_id == self.tenant_a.tenant_id,
                )
            )
            self.assertEqual(channel.tenant_id, self.tenant_a.tenant_id)
            self.assertEqual(quick_reply.tenant_id, self.tenant_a.tenant_id)

    def test_cross_tenant_ids_are_rejected_by_every_operational_route(self) -> None:
        tenant_b = self.tenant_b
        headers = self.headers_a

        requests = (
            self.client.get(
                f"/api/v1/channels/{tenant_b.channel_id}/status",
                headers=headers,
            ),
            self.client.get(
                f"/api/v1/channels/{tenant_b.channel_id}/qr",
                headers=headers,
            ),
            self.client.get(
                f"/api/v1/contacts/{tenant_b.contact_id}",
                headers=headers,
            ),
            self.client.post(
                f"/api/v1/contacts/{tenant_b.contact_id}/refresh",
                headers=headers,
                json={"channel_id": str(tenant_b.channel_id)},
            ),
            self.client.get(
                f"/api/v1/conversations/{tenant_b.conversation_id}",
                headers=headers,
            ),
            self.client.post(
                f"/api/v1/conversations/{tenant_b.conversation_id}/read",
                headers=headers,
            ),
            self.client.post(
                f"/api/v1/conversations/{tenant_b.conversation_id}/assign",
                headers=headers,
                json={},
            ),
            self.client.post(
                f"/api/v1/conversations/{tenant_b.conversation_id}/close",
                headers=headers,
            ),
            self.client.get(
                f"/api/v1/conversations/{tenant_b.conversation_id}/messages",
                headers=headers,
            ),
            self.client.post(
                f"/api/v1/conversations/{tenant_b.conversation_id}/messages",
                headers=headers,
                json={"text": "Tentativa cruzada"},
            ),
            self.client.post(
                f"/api/v1/conversations/{tenant_b.conversation_id}/attachments",
                headers=headers,
                files={"file": ("cross-tenant.txt", b"blocked", "text/plain")},
            ),
            self.client.post(
                f"/api/v1/conversations/{tenant_b.conversation_id}/messages/"
                f"{tenant_b.message_id}/retry",
                headers=headers,
            ),
        )

        for response in requests:
            with self.subTest(path=response.request.url.path):
                self.assertEqual(response.status_code, 404, response.text)

    def test_assignment_read_marker_and_login_cannot_cross_tenants(self) -> None:
        assignment = self.client.post(
            f"/api/v1/conversations/{self.tenant_a.conversation_id}/assign",
            headers=self.headers_a,
            json={"user_id": str(self.tenant_b.user_id)},
        )
        self.assertEqual(assignment.status_code, 400)
        self.assertEqual(assignment.json()["detail"], "Atendente fora do tenant")

        read = self.client.post(
            f"/api/v1/conversations/{self.tenant_a.conversation_id}/read",
            headers=self.headers_a,
        )
        self.assertEqual(read.status_code, 204)
        with SessionLocal() as db:
            marker = db.scalar(
                select(ConversationRead).where(
                    ConversationRead.tenant_id == self.tenant_a.tenant_id,
                    ConversationRead.conversation_id
                    == self.tenant_a.conversation_id,
                    ConversationRead.user_id == self.tenant_a.user_id,
                )
            )
            self.assertIsNotNone(marker)
            self.assertEqual(marker.tenant_id, self.tenant_a.tenant_id)

        wrong_membership = self.client.post(
            "/api/v1/auth/login",
            json={
                "email": self.tenant_a.email,
                "password": TEST_PASSWORD,
                "tenant_id": str(self.tenant_b.tenant_id),
            },
        )
        self.assertEqual(wrong_membership.status_code, 403)

    def test_assignment_cannot_be_stolen_and_only_assignee_can_operate(self) -> None:
        unassigned_send = self.client.post(
            f"/api/v1/conversations/{self.tenant_a.conversation_id}/messages",
            headers=self.headers_a,
            json={"text": "Não deve sair sem assumir"},
        )
        self.assertEqual(unassigned_send.status_code, 409)
        self.assertEqual(
            unassigned_send.json()["detail"],
            "Assuma o atendimento antes de continuar",
        )

        with SessionLocal() as db:
            second_user = User(
                email="second-agent-a@example.com",
                name="Segundo Agente A",
                password_hash=self.password_hash,
            )
            db.add(second_user)
            db.flush()
            db.add(
                TenantUser(
                    tenant_id=self.tenant_a.tenant_id,
                    user_id=second_user.id,
                    role="agent",
                )
            )
            db.commit()
            second_user_id = second_user.id

        login = self.client.post(
            "/api/v1/auth/login",
            json={
                "email": "second-agent-a@example.com",
                "password": TEST_PASSWORD,
                "tenant_id": str(self.tenant_a.tenant_id),
            },
        )
        self.assertEqual(login.status_code, 200, login.text)
        second_headers = {
            "Authorization": f"Bearer {login.json()['access_token']}"
        }

        unsupported_transfer = self.client.post(
            f"/api/v1/conversations/{self.tenant_a.conversation_id}/assign",
            headers=self.headers_a,
            json={"user_id": str(second_user_id)},
        )
        self.assertEqual(unsupported_transfer.status_code, 403)
        self.assertEqual(
            unsupported_transfer.json()["detail"],
            "Transferência de atendimento não disponível no MVP",
        )

        assigned = self.client.post(
            f"/api/v1/conversations/{self.tenant_a.conversation_id}/assign",
            headers=self.headers_a,
            json={},
        )
        self.assertEqual(assigned.status_code, 200, assigned.text)
        self.assertEqual(
            assigned.json()["assigned_user_id"],
            str(self.tenant_a.user_id),
        )

        takeover = self.client.post(
            f"/api/v1/conversations/{self.tenant_a.conversation_id}/assign",
            headers=second_headers,
            json={"user_id": str(second_user_id)},
        )
        self.assertEqual(takeover.status_code, 409)
        self.assertEqual(
            takeover.json()["detail"],
            "Atendimento já assumido por outro agente",
        )

        forbidden_send = self.client.post(
            f"/api/v1/conversations/{self.tenant_a.conversation_id}/messages",
            headers=second_headers,
            json={"text": "Não deve sair por outro agente"},
        )
        forbidden_close = self.client.post(
            f"/api/v1/conversations/{self.tenant_a.conversation_id}/close",
            headers=second_headers,
        )
        self.assertEqual(forbidden_send.status_code, 409)
        self.assertEqual(forbidden_close.status_code, 409)
        self.assertEqual(
            forbidden_send.json()["detail"],
            "Atendimento já assumido por outro agente",
        )
        self.assertEqual(
            forbidden_close.json()["detail"],
            "Atendimento já assumido por outro agente",
        )

    def test_websocket_revalidates_membership_instead_of_trusting_token_claim(self) -> None:
        forged_token = create_access_token(
            str(self.tenant_a.user_id),
            str(self.tenant_b.tenant_id),
            role="admin",
        )

        with self.assertRaises(WebSocketDisconnect) as raised:
            with self.client.websocket_connect(
                f"/ws?token={quote(forged_token)}"
            ):
                pass

        self.assertEqual(raised.exception.code, 1008)
