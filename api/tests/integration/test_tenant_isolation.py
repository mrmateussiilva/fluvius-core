from unittest.mock import AsyncMock, Mock, patch
from uuid import UUID

from sqlalchemy import select
from starlette.websockets import WebSocketDisconnect

from app.channels.models import WhatsAppChannel
from app.common.audit_models import AuditLog
from app.common.enums import ChannelStatus, ConversationStatus
from app.config import settings
from app.conversations.models import Conversation, ConversationRead
from app.database import SessionLocal
from app.messages.models import Message
from app.providers.base import QRCodeResult
from app.providers.evolution_credentials import decrypt_provider_secret
from app.providers.factory import get_provider
from app.providers.models import ProviderCredential
from app.quick_replies.models import QuickReply
from app.security import create_access_token
from app.users.models import TenantUser, User

from .base import TEST_PASSWORD, PostgresIntegrationTestCase


class TenantIsolationTest(PostgresIntegrationTestCase):
    def test_admin_manages_only_the_users_from_its_tenant(self) -> None:
        created = self.client.post(
            "/api/v1/users",
            headers=self.headers_a,
            json={
                "name": "Atendente Empresa A",
                "email": "atendente-a@example.com",
                "password": "senha-temporaria-123",
                "role": "agent",
            },
        )
        self.assertEqual(created.status_code, 201, created.text)
        created_user_id = UUID(created.json()["id"])
        self.assertEqual(created.json()["role"], "agent")
        self.assertTrue(created.json()["is_active"])

        tenant_a_users = self.client.get("/api/v1/users", headers=self.headers_a)
        tenant_b_users = self.client.get("/api/v1/users", headers=self.headers_b)
        self.assertEqual(tenant_a_users.status_code, 200, tenant_a_users.text)
        self.assertEqual(tenant_b_users.status_code, 200, tenant_b_users.text)
        self.assertEqual(
            {user["id"] for user in tenant_a_users.json()},
            {str(self.tenant_a.user_id), str(created_user_id)},
        )
        self.assertNotIn(
            str(created_user_id),
            {user["id"] for user in tenant_b_users.json()},
        )

        login = self.client.post(
            "/api/v1/auth/login",
            json={
                "email": "atendente-a@example.com",
                "password": "senha-temporaria-123",
                "tenant_id": str(self.tenant_a.tenant_id),
            },
        )
        self.assertEqual(login.status_code, 200, login.text)
        agent_headers = {
            "Authorization": f"Bearer {login.json()['access_token']}"
        }
        active_team = self.client.get(
            "/api/v1/users/active",
            headers=self.headers_a,
        )
        self.assertEqual(active_team.status_code, 200, active_team.text)
        self.assertEqual(
            {user["id"] for user in active_team.json()},
            {str(self.tenant_a.user_id), str(created_user_id)},
        )
        self.assertTrue(
            all(
                set(user) == {"id", "name", "role"}
                for user in active_team.json()
            )
        )
        tenant_b_active_team = self.client.get(
            "/api/v1/users/active",
            headers=self.headers_b,
        )
        self.assertEqual(
            {user["id"] for user in tenant_b_active_team.json()},
            {str(self.tenant_b.user_id)},
        )
        self.assertEqual(
            self.client.get(
                "/api/v1/users/active",
                headers=agent_headers,
            ).status_code,
            403,
        )
        self.assertEqual(
            self.client.get("/api/v1/users", headers=agent_headers).status_code,
            403,
        )
        self.assertEqual(
            self.client.post(
                "/api/v1/users",
                headers=agent_headers,
                json={
                    "name": "Usuário indevido",
                    "email": "indevido@example.com",
                    "password": "senha-indesejada",
                },
            ).status_code,
            403,
        )

        cross_tenant = self.client.patch(
            f"/api/v1/users/{created_user_id}",
            headers=self.headers_b,
            json={"name": "Tentativa cruzada"},
        )
        self.assertEqual(cross_tenant.status_code, 404, cross_tenant.text)

        with SessionLocal() as db:
            conversation = db.scalar(
                select(Conversation).where(
                    Conversation.id == self.tenant_a.conversation_id,
                    Conversation.tenant_id == self.tenant_a.tenant_id,
                )
            )
            conversation.status = ConversationStatus.OPEN
            conversation.assigned_user_id = created_user_id
            db.commit()

        deactivated = self.client.patch(
            f"/api/v1/users/{created_user_id}",
            headers=self.headers_a,
            json={"is_active": False},
        )
        self.assertEqual(deactivated.status_code, 200, deactivated.text)
        self.assertFalse(deactivated.json()["is_active"])
        self.assertEqual(
            self.client.get("/api/v1/auth/me", headers=agent_headers).status_code,
            401,
        )
        inactive_assignment = self.client.post(
            f"/api/v1/conversations/{self.tenant_a.conversation_id}/assign",
            headers=self.headers_a,
            json={"user_id": str(created_user_id)},
        )
        self.assertEqual(inactive_assignment.status_code, 400)
        self.assertEqual(
            inactive_assignment.json()["detail"],
            "Atendente fora do tenant",
        )
        active_team_after_deactivation = self.client.get(
            "/api/v1/users/active",
            headers=self.headers_a,
        )
        self.assertEqual(
            {user["id"] for user in active_team_after_deactivation.json()},
            {str(self.tenant_a.user_id)},
        )
        with SessionLocal() as db:
            conversation = db.scalar(
                select(Conversation).where(
                    Conversation.id == self.tenant_a.conversation_id,
                    Conversation.tenant_id == self.tenant_a.tenant_id,
                )
            )
            self.assertEqual(conversation.status, ConversationStatus.NEW)
            self.assertIsNone(conversation.assigned_user_id)

        reactivated = self.client.patch(
            f"/api/v1/users/{created_user_id}",
            headers=self.headers_a,
            json={
                "is_active": True,
                "password": "nova-senha-temporaria-456",
            },
        )
        self.assertEqual(reactivated.status_code, 200, reactivated.text)
        relogin = self.client.post(
            "/api/v1/auth/login",
            json={
                "email": "atendente-a@example.com",
                "password": "nova-senha-temporaria-456",
                "tenant_id": str(self.tenant_a.tenant_id),
            },
        )
        self.assertEqual(relogin.status_code, 200, relogin.text)

        self_change = self.client.patch(
            f"/api/v1/users/{self.tenant_a.user_id}",
            headers=self.headers_a,
            json={"role": "agent"},
        )
        self.assertEqual(self_change.status_code, 409, self_change.text)

        duplicate = self.client.post(
            "/api/v1/users",
            headers=self.headers_a,
            json={
                "name": "E-mail duplicado",
                "email": "atendente-a@example.com",
                "password": "outra-senha-temporaria",
            },
        )
        self.assertEqual(duplicate.status_code, 409, duplicate.text)

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

        with patch.object(
            settings,
            "evolution_go_instance_tokens",
            {
                "tenant-a": "token-a",
                "tenant-b": "token-b",
                "tenant-a-extra": "token-a-extra",
            },
        ):
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

    def test_admin_provisions_a_managed_evolution_channel_idempotently(self) -> None:
        provisioning_key = "a0ca3990-b622-43f6-a8f9-f2ae70a587ee"
        with patch(
            "app.providers.evolution_provisioning.EvolutionGoAdminClient.create_instance",
            new_callable=AsyncMock,
        ) as create_instance:
            first = self.client.post(
                "/api/v1/channels",
                headers=self.headers_a,
                json={
                    "name": "Comercial",
                    "phone_number": "5527999999999",
                    "provider": "evolution_go",
                    "provisioning_key": provisioning_key,
                },
            )
            second = self.client.post(
                "/api/v1/channels",
                headers=self.headers_a,
                json={
                    "name": "Comercial",
                    "phone_number": "5527999999999",
                    "provider": "evolution_go",
                    "provisioning_key": provisioning_key,
                },
            )

        self.assertEqual(first.status_code, 201, first.text)
        self.assertEqual(second.status_code, 200, second.text)
        self.assertEqual(first.json()["id"], second.json()["id"])
        self.assertNotIn("token", first.text.lower())
        create_instance.assert_awaited_once()
        provisioned = create_instance.await_args.args[0]
        self.assertEqual(provisioned.instance_id, first.json()["id"])

        with SessionLocal() as db:
            credential = db.scalar(
                select(ProviderCredential).where(
                    ProviderCredential.tenant_id == self.tenant_a.tenant_id,
                    ProviderCredential.channel_id == UUID(first.json()["id"]),
                )
            )
            self.assertIsNotNone(credential)
            self.assertEqual(credential.provisioning_status, "active")
            self.assertNotIn(provisioned.token.encode(), credential.encrypted_secret)
            self.assertEqual(
                decrypt_provider_secret(credential.encrypted_secret),
                provisioned.token,
            )
            channel = db.scalar(
                select(WhatsAppChannel).where(
                    WhatsAppChannel.tenant_id == self.tenant_a.tenant_id,
                    WhatsAppChannel.id == UUID(first.json()["id"]),
                )
            )
            self.assertEqual(
                get_provider(channel.provider, channel, db).api_key,
                provisioned.token,
            )
            audit = db.scalar(
                select(AuditLog).where(
                    AuditLog.tenant_id == self.tenant_a.tenant_id,
                    AuditLog.entity_id == UUID(first.json()["id"]),
                    AuditLog.action == "channel.provisioned",
                )
            )
            self.assertIsNotNone(audit)

    def test_agent_cannot_create_or_connect_channels(self) -> None:
        with SessionLocal() as db:
            agent = User(
                email="channel-agent@example.com",
                name="Atendente",
                password_hash=self.password_hash,
            )
            db.add(agent)
            db.flush()
            db.add(
                TenantUser(
                    tenant_id=self.tenant_a.tenant_id,
                    user_id=agent.id,
                    role="agent",
                )
            )
            db.commit()
            agent_id = agent.id

        agent_headers = {
            "Authorization": (
                "Bearer "
                + create_access_token(
                    str(agent_id),
                    str(self.tenant_a.tenant_id),
                    role="agent",
                )
            )
        }
        created = self.client.post(
            "/api/v1/channels",
            headers=agent_headers,
            json={"name": "Não autorizado", "provider": "evolution_go"},
        )
        connected = self.client.post(
            f"/api/v1/channels/{self.tenant_a.channel_id}/connect",
            headers=agent_headers,
        )

        self.assertEqual(created.status_code, 403, created.text)
        self.assertEqual(connected.status_code, 403, connected.text)

    def test_reuses_the_channel_that_already_owns_the_evolution_credential(self) -> None:
        with patch.object(
            settings,
            "evolution_go_instance_tokens",
            {
                "tenant-a": "token-a",
                "tenant-b": "token-b",
                "tenant-a-copy": "token-a",
            },
        ):
            response = self.client.post(
                "/api/v1/channels",
                headers=self.headers_a,
                json={
                    "name": "Cópia insegura",
                    "provider": "evolution_go",
                    "provider_config": {"instance_name": "tenant-a-copy"},
                },
            )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["id"], str(self.tenant_a.channel_id))
        self.assertEqual(response.json()["name"], "Canal A")

    def test_evolution_credential_cannot_cross_tenants(self) -> None:
        with patch.object(
            settings,
            "evolution_go_instance_tokens",
            {
                "tenant-a": "token-a",
                "tenant-b": "token-b",
                "foreign-copy": "token-b",
            },
        ):
            response = self.client.post(
                "/api/v1/channels",
                headers=self.headers_a,
                json={
                    "name": "Cópia cruzada",
                    "provider": "evolution_go",
                    "provider_config": {"instance_name": "foreign-copy"},
                },
            )

        self.assertEqual(response.status_code, 409)
        self.assertEqual(
            response.json()["detail"],
            "Esta credencial Evolution já está associada a outro canal",
        )

    def test_connects_channel_through_tenant_scoped_api(self) -> None:
        provider = Mock()
        provider.get_qr_code = AsyncMock(
            return_value=QRCodeResult(
                qr_code="cXItY29kZS1pbWFnZQ==",
                pairing_code="1234-5678",
                status=ChannelStatus.REQUIRES_QR,
            )
        )
        with (
            patch.object(
                settings,
                "evolution_go_instance_tokens",
                {"tenant-a": "token-a", "tenant-b": "token-b"},
            ),
            patch("app.channels.router.get_provider", return_value=provider),
        ):
            response = self.client.post(
                f"/api/v1/channels/{self.tenant_a.channel_id}/connect",
                headers=self.headers_a,
            )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["status"], "requires_qr")
        self.assertEqual(response.json()["pairing_code"], "1234-5678")
        provider.get_qr_code.assert_awaited_once()
        with SessionLocal() as db:
            channel = db.scalar(
                select(WhatsAppChannel).where(
                    WhatsAppChannel.id == self.tenant_a.channel_id,
                    WhatsAppChannel.tenant_id == self.tenant_a.tenant_id,
                )
            )
            self.assertEqual(channel.status, ChannelStatus.REQUIRES_QR)

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
            self.client.post(
                f"/api/v1/channels/{tenant_b.channel_id}/connect",
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
                f"/api/v1/conversations/{tenant_b.conversation_id}/release",
                headers=headers,
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
            json={"through_message_id": str(self.tenant_a.message_id)},
        )
        self.assertEqual(read.status_code, 204)
        foreign_visible_message = self.client.post(
            f"/api/v1/conversations/{self.tenant_a.conversation_id}/read",
            headers=self.headers_a,
            json={"through_message_id": str(self.tenant_b.message_id)},
        )
        self.assertEqual(foreign_visible_message.status_code, 404)
        with SessionLocal() as db:
            marker = db.scalar(
                select(ConversationRead).where(
                    ConversationRead.tenant_id == self.tenant_a.tenant_id,
                    ConversationRead.conversation_id
                    == self.tenant_a.conversation_id,
                    ConversationRead.user_id == self.tenant_a.user_id,
                )
            )
            visible_message = db.scalar(
                select(Message).where(
                    Message.id == self.tenant_a.message_id,
                    Message.tenant_id == self.tenant_a.tenant_id,
                    Message.conversation_id
                    == self.tenant_a.conversation_id,
                )
            )
            self.assertIsNotNone(marker)
            self.assertEqual(marker.tenant_id, self.tenant_a.tenant_id)
            self.assertEqual(marker.last_read_at, visible_message.created_at)

        wrong_membership = self.client.post(
            "/api/v1/auth/login",
            json={
                "email": self.tenant_a.email,
                "password": TEST_PASSWORD,
                "tenant_id": str(self.tenant_b.tenant_id),
            },
        )
        self.assertEqual(wrong_membership.status_code, 403)

    def test_admin_can_transfer_and_take_over_but_agent_cannot_steal(self) -> None:
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

        transferred = self.client.post(
            f"/api/v1/conversations/{self.tenant_a.conversation_id}/assign",
            headers=self.headers_a,
            json={"user_id": str(second_user_id)},
        )
        self.assertEqual(transferred.status_code, 200, transferred.text)
        self.assertEqual(
            transferred.json()["assigned_user_id"],
            str(second_user_id),
        )

        forbidden_transfer = self.client.post(
            f"/api/v1/conversations/{self.tenant_a.conversation_id}/assign",
            headers=second_headers,
            json={"user_id": str(self.tenant_a.user_id)},
        )
        self.assertEqual(forbidden_transfer.status_code, 403)
        self.assertEqual(
            forbidden_transfer.json()["detail"],
            "Apenas administradores podem transferir atendimentos",
        )
        forbidden_release = self.client.post(
            f"/api/v1/conversations/{self.tenant_a.conversation_id}/release",
            headers=second_headers,
        )
        self.assertEqual(forbidden_release.status_code, 403)
        self.assertEqual(
            forbidden_release.json()["detail"],
            "Apenas administradores podem liberar atendimentos",
        )

        admin_takeover = self.client.post(
            f"/api/v1/conversations/{self.tenant_a.conversation_id}/assign",
            headers=self.headers_a,
            json={},
        )
        self.assertEqual(admin_takeover.status_code, 200, admin_takeover.text)
        self.assertEqual(
            admin_takeover.json()["assigned_user_id"],
            str(self.tenant_a.user_id),
        )

        forbidden_takeover = self.client.post(
            f"/api/v1/conversations/{self.tenant_a.conversation_id}/assign",
            headers=second_headers,
            json={},
        )
        self.assertEqual(forbidden_takeover.status_code, 409)
        self.assertEqual(
            forbidden_takeover.json()["detail"],
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
        released = self.client.post(
            f"/api/v1/conversations/{self.tenant_a.conversation_id}/release",
            headers=self.headers_a,
        )
        self.assertEqual(released.status_code, 200, released.text)
        self.assertEqual(released.json()["status"], "new")
        self.assertIsNone(released.json()["assigned_user_id"])
        with SessionLocal() as db:
            assignment_logs = list(
                db.scalars(
                    select(AuditLog)
                    .where(
                        AuditLog.tenant_id == self.tenant_a.tenant_id,
                        AuditLog.entity_id == self.tenant_a.conversation_id,
                    )
                    .order_by(AuditLog.created_at)
                )
            )
        self.assertEqual(
            [
                log.metadata_["mode"]
                for log in assignment_logs
                if log.action == "conversation.assigned"
            ],
            ["transfer", "takeover"],
        )
        self.assertTrue(
            all(log.user_id == self.tenant_a.user_id for log in assignment_logs)
        )
        self.assertEqual(
            [log.action for log in assignment_logs],
            [
                "conversation.assigned",
                "conversation.assigned",
                "conversation.released",
            ],
        )

    def test_websocket_revalidates_membership_instead_of_trusting_token_claim(self) -> None:
        valid_token = create_access_token(
            str(self.tenant_a.user_id),
            str(self.tenant_a.tenant_id),
            role="admin",
        )
        with self.client.websocket_connect(
            "/ws",
            subprotocols=["fluvius-auth", valid_token],
        ) as websocket:
            self.assertEqual(
                websocket.accepted_subprotocol,
                "fluvius-auth",
            )

        forged_token = create_access_token(
            str(self.tenant_a.user_id),
            str(self.tenant_b.tenant_id),
            role="admin",
        )

        with self.assertRaises(WebSocketDisconnect) as raised:
            with self.client.websocket_connect(
                "/ws",
                subprotocols=["fluvius-auth", forged_token],
            ):
                pass

        self.assertEqual(raised.exception.code, 1008)
