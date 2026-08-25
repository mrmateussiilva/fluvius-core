import os
import unittest
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from uuid import UUID

from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.engine import make_url

from app.channels.models import WhatsAppChannel
from app.common.enums import (
    ChannelProvider,
    ChannelStatus,
    ConversationStatus,
    MessageDirection,
    MessageStatus,
    MessageType,
)
from app.config import settings
from app.contacts.models import Contact
from app.conversations.models import Conversation
from app.database import Base, SessionLocal, engine, load_all_models
from app.main import app
from app.messages.models import Message
from app.providers.inbox_tasks import run_provider_event_inbox
from app.providers.models import ProviderEventInbox
from app.quick_replies.models import QuickReply
from app.security import hash_password
from app.tenants.models import Tenant
from app.users.models import TenantUser, User

TEST_PASSWORD = "integration-password"


@dataclass(frozen=True)
class TenantFixture:
    tenant_id: UUID
    user_id: UUID
    email: str
    channel_id: UUID
    contact_id: UUID
    conversation_id: UUID
    message_id: UUID
    quick_reply_id: UUID


class PostgresIntegrationTestCase(unittest.TestCase):
    client: TestClient
    password_hash: str
    tenant_a: TenantFixture
    tenant_b: TenantFixture
    headers_a: dict[str, str]
    headers_b: dict[str, str]

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        if os.getenv("RUN_INTEGRATION_TESTS") != "1":
            raise unittest.SkipTest("Defina RUN_INTEGRATION_TESTS=1 para testes PostgreSQL")

        database_name = make_url(settings.database_url).database or ""
        if settings.environment != "test" or not database_name.endswith("_test"):
            raise RuntimeError(
                "Testes de integração exigem ENVIRONMENT=test e banco com sufixo '_test'"
            )

        load_all_models()
        with engine.connect() as connection:
            revision = connection.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar_one()
        if revision != "20260824_0028":
            raise RuntimeError(f"Schema de teste está na revisão inesperada {revision}")

        cls.password_hash = hash_password(TEST_PASSWORD)
        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls) -> None:
        if hasattr(cls, "client"):
            cls.client.close()
        engine.dispose()
        super().tearDownClass()

    def setUp(self) -> None:
        self._clear_database()
        self.tenant_a = self._create_tenant_fixture("a", "5527991111111")
        self.tenant_b = self._create_tenant_fixture("b", "5527992222222")
        self.headers_a = self._login_headers(self.tenant_a)
        self.headers_b = self._login_headers(self.tenant_b)

    def _clear_database(self) -> None:
        table_names = ", ".join(f'"{table.name}"' for table in Base.metadata.sorted_tables)
        with engine.begin() as connection:
            connection.execute(text(f"TRUNCATE TABLE {table_names} CASCADE"))

    def post_webhook(self, url: str, payload: dict, *, process: bool = True):
        response = self.client.post(url, json=payload)
        if process and response.status_code == 202:
            self.process_pending_webhook_inbox()
        return response

    def process_pending_webhook_inbox(self) -> int:
        with SessionLocal() as db:
            pending = list(
                db.execute(
                    select(
                        ProviderEventInbox.id,
                        ProviderEventInbox.tenant_id,
                    )
                    .where(ProviderEventInbox.status.in_(("queued", "enqueued", "retry_wait")))
                    .order_by(ProviderEventInbox.created_at)
                )
            )
        return sum(
            run_provider_event_inbox(str(inbox_id), str(tenant_id))
            for inbox_id, tenant_id in pending
        )

    def _create_tenant_fixture(self, label: str, phone_number: str) -> TenantFixture:
        now = datetime.now(UTC)
        with SessionLocal() as db:
            tenant = Tenant(name=f"Tenant {label.upper()}", slug=f"tenant-{label}")
            user = User(
                email=f"agent-{label}@example.com",
                name=f"Agente {label.upper()}",
                password_hash=self.password_hash,
            )
            db.add_all([tenant, user])
            db.flush()

            membership = TenantUser(
                tenant_id=tenant.id,
                user_id=user.id,
                role="admin",
            )
            channel = WhatsAppChannel(
                tenant_id=tenant.id,
                name=f"Canal {label.upper()}",
                phone_number=f"5527888{'2' if label == 'b' else '1'}0000",
                provider=ChannelProvider.EVOLUTION_GO,
                provider_config={"instance_name": f"tenant-{label}"},
                credential_fingerprint=sha256(f"token-{label}".encode()).hexdigest(),
                status=ChannelStatus.CONNECTED,
            )
            contact = Contact(
                tenant_id=tenant.id,
                name=f"Contato {label.upper()}",
                phone_number=phone_number,
            )
            db.add_all([membership, channel, contact])
            db.flush()

            conversation = Conversation(
                tenant_id=tenant.id,
                channel_id=channel.id,
                contact_id=contact.id,
                status=ConversationStatus.NEW,
                last_message_at=now,
            )
            db.add(conversation)
            db.flush()

            message = Message(
                tenant_id=tenant.id,
                conversation_id=conversation.id,
                direction=MessageDirection.INCOMING,
                message_type=MessageType.TEXT,
                status=MessageStatus.DELIVERED,
                body=f"Mensagem do tenant {label.upper()}",
                provider_message_id=f"seed-{label}",
                sent_at=now,
            )
            quick_reply = QuickReply(
                tenant_id=tenant.id,
                created_by_user_id=user.id,
                shortcut=f"/ola-{label}",
                title=f"Olá {label.upper()}",
                content=f"Resposta do tenant {label.upper()}",
            )
            db.add_all([message, quick_reply])
            db.commit()

            return TenantFixture(
                tenant_id=tenant.id,
                user_id=user.id,
                email=user.email,
                channel_id=channel.id,
                contact_id=contact.id,
                conversation_id=conversation.id,
                message_id=message.id,
                quick_reply_id=quick_reply.id,
            )

    def _login_headers(self, fixture: TenantFixture) -> dict[str, str]:
        response = self.client.post(
            "/api/v1/auth/login",
            json={
                "email": fixture.email,
                "password": TEST_PASSWORD,
                "tenant_id": str(fixture.tenant_id),
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        return {"Authorization": f"Bearer {response.json()['access_token']}"}
