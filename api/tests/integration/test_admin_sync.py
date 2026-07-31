from unittest.mock import AsyncMock, Mock, patch
from uuid import UUID

from sqlalchemy import select

from app.channels.models import WhatsAppChannel
from app.common.audit_models import AuditLog
from app.common.enums import (
    ChannelStatus,
    ContactKind,
    ConversationStatus,
    MessageDirection,
    MessageStatus,
    MessageType,
)
from app.contacts.models import Contact
from app.conversations.models import Conversation
from app.database import SessionLocal
from app.messages.models import Message
from app.providers.base import ContactProfileResult, GroupDirectoryEntry, GroupMemberProfile
from app.providers.models import ProviderEvent
from app.sync.models import SyncRun
from app.sync.tasks import (
    PENDING_MESSAGE_ERRORS,
    run_sync,
)
from app.users.models import TenantUser, User

from .base import TEST_PASSWORD, PostgresIntegrationTestCase


class AdminSyncTest(PostgresIntegrationTestCase):
    def _create_agent_headers(self) -> dict[str, str]:
        with SessionLocal() as db:
            user = User(
                email="sync-agent@example.com",
                name="Atendente Sync",
                password_hash=self.password_hash,
            )
            db.add(user)
            db.flush()
            db.add(
                TenantUser(
                    tenant_id=self.tenant_a.tenant_id,
                    user_id=user.id,
                    role="agent",
                )
            )
            db.commit()
        login = self.client.post(
            "/api/v1/auth/login",
            json={
                "email": "sync-agent@example.com",
                "password": TEST_PASSWORD,
                "tenant_id": str(self.tenant_a.tenant_id),
            },
        )
        self.assertEqual(login.status_code, 200, login.text)
        return {"Authorization": f"Bearer {login.json()['access_token']}"}

    def _request_run(self, sync_type: str, recent_days: int = 7) -> dict:
        with patch(
            "app.sync.router.default_queue.enqueue",
            return_value=Mock(id=f"rq-{sync_type}"),
        ):
            response = self.client.post(
                "/api/v1/admin/sync-runs",
                headers=self.headers_a,
                json={
                    "channel_id": str(self.tenant_a.channel_id),
                    "sync_type": sync_type,
                    "recent_days": recent_days,
                },
            )
        self.assertEqual(response.status_code, 202, response.text)
        return response.json()

    def test_sync_routes_are_admin_only_tenant_scoped_and_single_flight(self) -> None:
        agent_headers = self._create_agent_headers()
        forbidden = self.client.post(
            "/api/v1/admin/sync-runs",
            headers=agent_headers,
            json={
                "channel_id": str(self.tenant_a.channel_id),
                "sync_type": "messages",
            },
        )
        self.assertEqual(forbidden.status_code, 403)

        cross_tenant = self.client.post(
            "/api/v1/admin/sync-runs",
            headers=self.headers_a,
            json={
                "channel_id": str(self.tenant_b.channel_id),
                "sync_type": "messages",
            },
        )
        self.assertEqual(cross_tenant.status_code, 404)

        with SessionLocal() as db:
            channel = db.scalar(
                select(WhatsAppChannel).where(
                    WhatsAppChannel.id == self.tenant_a.channel_id,
                    WhatsAppChannel.tenant_id == self.tenant_a.tenant_id,
                )
            )
            channel.status = ChannelStatus.DISCONNECTED
            db.commit()
        offline_contacts = self.client.post(
            "/api/v1/admin/sync-runs",
            headers=self.headers_a,
            json={
                "channel_id": str(self.tenant_a.channel_id),
                "sync_type": "contacts",
            },
        )
        self.assertEqual(offline_contacts.status_code, 409)

        run = self._request_run("messages", recent_days=3)
        self.assertEqual(run["status"], "queued")
        self.assertEqual(run["recent_days"], 3)
        with patch(
            "app.sync.router.default_queue.enqueue",
            return_value=Mock(id="rq-duplicate"),
        ):
            duplicate = self.client.post(
                "/api/v1/admin/sync-runs",
                headers=self.headers_a,
                json={
                    "channel_id": str(self.tenant_a.channel_id),
                    "sync_type": "messages",
                },
            )
        self.assertEqual(duplicate.status_code, 409)

        tenant_a_runs = self.client.get(
            "/api/v1/admin/sync-runs",
            headers=self.headers_a,
        )
        tenant_b_runs = self.client.get(
            "/api/v1/admin/sync-runs",
            headers=self.headers_b,
        )
        self.assertEqual({item["id"] for item in tenant_a_runs.json()}, {run["id"]})
        self.assertEqual(tenant_b_runs.json(), [])
        with SessionLocal() as db:
            audit = db.scalar(
                select(AuditLog).where(
                    AuditLog.tenant_id == self.tenant_a.tenant_id,
                    AuditLog.entity_id == UUID(run["id"]),
                    AuditLog.action == "sync.requested",
                )
            )
            self.assertIsNotNone(audit)

    def test_contact_sync_runs_in_worker_and_persists_progress(self) -> None:
        run = self._request_run("contacts")
        provider = Mock()
        provider.get_contact_profile = AsyncMock(
            return_value=ContactProfileResult(
                push_name="Contato Sincronizado",
                about="Perfil atualizado",
                is_on_whatsapp=True,
            )
        )
        provider.list_groups = AsyncMock(
            return_value=[
                GroupDirectoryEntry(
                    group_id="120363018686549942",
                    provider_address="120363018686549942@g.us",
                    name="Grupo sem conversa",
                    member_count=3,
                    members=[
                        GroupMemberProfile(
                            phone_number="5527999999999",
                            name="Admin Grupo",
                            is_admin=True,
                        )
                    ],
                )
            ]
        )
        with (
            patch("app.contacts.service.get_provider", return_value=provider),
            patch("app.contacts.service.claim_evolution_credential"),
        ):
            run_sync(run["id"], str(self.tenant_a.tenant_id))

        with SessionLocal() as db:
            persisted = db.scalar(
                select(SyncRun).where(
                    SyncRun.id == UUID(run["id"]),
                    SyncRun.tenant_id == self.tenant_a.tenant_id,
                )
            )
            contact = db.scalar(
                select(Contact).where(
                    Contact.id == self.tenant_a.contact_id,
                    Contact.tenant_id == self.tenant_a.tenant_id,
                )
            )
            self.assertEqual(persisted.status, "completed")
            self.assertEqual(persisted.total_items, 1)
            self.assertEqual(persisted.contact_items, 1)
            self.assertEqual(persisted.group_items, 0)
            self.assertEqual(persisted.message_event_items, 0)
            self.assertEqual(persisted.imported_group_items, 1)
            self.assertEqual(persisted.succeeded_items, 1)
            self.assertEqual(persisted.failed_items, 0)
            self.assertEqual(contact.push_name, "Contato Sincronizado")
            self.assertEqual(contact.about, "Perfil atualizado")
            self.assertIsNotNone(contact.profile_synced_at)
            imported_group = db.scalar(
                select(Contact).where(
                    Contact.tenant_id == self.tenant_a.tenant_id,
                    Contact.phone_number == "120363018686549942",
                )
            )
            self.assertIsNotNone(imported_group)
            self.assertEqual(imported_group.kind, ContactKind.GROUP)
            self.assertEqual(imported_group.group_member_count, 3)

    def test_contact_sync_includes_known_group_conversations(self) -> None:
        with SessionLocal() as db:
            group = Contact(
                tenant_id=self.tenant_a.tenant_id,
                kind=ContactKind.GROUP,
                name="Grupo 654321",
                phone_number="120363018686549942",
                provider_address="120363018686549942@g.us",
            )
            db.add(group)
            db.flush()
            db.add(
                Conversation(
                    tenant_id=self.tenant_a.tenant_id,
                    channel_id=self.tenant_a.channel_id,
                    contact_id=group.id,
                    status=ConversationStatus.NEW,
                )
            )
            db.commit()

        run = self._request_run("contacts")
        provider = Mock()
        provider.get_contact_profile = AsyncMock(
            return_value=ContactProfileResult(push_name="Contato Sincronizado")
        )
        provider.get_group_profile = AsyncMock(
            return_value=ContactProfileResult(
                push_name="Grupo Comercial",
                about="Atendimento B2B",
                group_member_count=12,
                group_members=[
                    GroupMemberProfile(
                        phone_number="5527999999999",
                        name="Coordenador",
                        is_admin=True,
                    )
                ],
            )
        )
        provider.list_groups = AsyncMock(return_value=[])
        with (
            patch("app.contacts.service.get_provider", return_value=provider),
            patch("app.contacts.service.claim_evolution_credential"),
        ):
            run_sync(run["id"], str(self.tenant_a.tenant_id))

        with SessionLocal() as db:
            persisted = db.scalar(
                select(SyncRun).where(
                    SyncRun.id == UUID(run["id"]),
                    SyncRun.tenant_id == self.tenant_a.tenant_id,
                )
            )
            group = db.scalar(
                select(Contact).where(
                    Contact.tenant_id == self.tenant_a.tenant_id,
                    Contact.phone_number == "120363018686549942",
                )
            )
            self.assertEqual(persisted.status, "completed")
            self.assertEqual(persisted.total_items, 2)
            self.assertEqual(persisted.contact_items, 1)
            self.assertEqual(persisted.group_items, 1)
            self.assertEqual(persisted.message_event_items, 0)
            self.assertEqual(persisted.imported_group_items, 0)
            self.assertEqual(persisted.succeeded_items, 2)
            self.assertEqual(group.name, "Grupo Comercial")
            self.assertEqual(group.about, "Atendimento B2B")
            self.assertEqual(group.group_member_count, 12)
            self.assertEqual(group.group_members[0]["name"], "Coordenador")
            provider.get_group_profile.assert_awaited_once()

    def test_message_sync_reconciles_recent_pending_receipt(self) -> None:
        with SessionLocal() as db:
            message = Message(
                tenant_id=self.tenant_a.tenant_id,
                conversation_id=self.tenant_a.conversation_id,
                direction=MessageDirection.OUTGOING,
                message_type=MessageType.TEXT,
                status=MessageStatus.SENT,
                body="Mensagem aguardando recibo",
                provider_message_id="sync-outgoing-1",
            )
            event = ProviderEvent(
                tenant_id=self.tenant_a.tenant_id,
                channel_id=self.tenant_a.channel_id,
                provider="evolution_go",
                event_type="Receipt",
                provider_event_id="sync-receipt-1",
                payload={
                    "event": "Receipt",
                    "state": "Delivered",
                    "data": {
                        "MessageIDs": ["sync-outgoing-1"],
                        "Timestamp": "2026-07-27T00:00:00-03:00",
                        "Type": "delivered",
                    },
                },
                processed=False,
                processing_error=PENDING_MESSAGE_ERRORS[0],
            )
            db.add_all([message, event])
            db.commit()
            message_id = message.id
            event_id = event.id

        run = self._request_run("messages")
        with patch("app.sync.tasks.claim_evolution_credential"):
            run_sync(run["id"], str(self.tenant_a.tenant_id))

        with SessionLocal() as db:
            persisted = db.scalar(
                select(SyncRun).where(
                    SyncRun.id == UUID(run["id"]),
                    SyncRun.tenant_id == self.tenant_a.tenant_id,
                )
            )
            message = db.scalar(
                select(Message).where(
                    Message.id == message_id,
                    Message.tenant_id == self.tenant_a.tenant_id,
                )
            )
            event = db.scalar(
                select(ProviderEvent).where(
                    ProviderEvent.id == event_id,
                    ProviderEvent.tenant_id == self.tenant_a.tenant_id,
                )
            )
            self.assertEqual(persisted.status, "completed")
            self.assertEqual(persisted.total_items, 1)
            self.assertEqual(persisted.contact_items, 0)
            self.assertEqual(persisted.group_items, 0)
            self.assertEqual(persisted.message_event_items, 1)
            self.assertEqual(persisted.imported_group_items, 0)
            self.assertEqual(persisted.succeeded_items, 1)
            self.assertEqual(message.status, MessageStatus.DELIVERED)
            self.assertIsNotNone(message.delivered_at)
            self.assertTrue(event.processed)
            self.assertIsNone(event.processing_error)
