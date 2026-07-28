from datetime import UTC, datetime, timedelta
from unittest.mock import patch

from sqlalchemy import select

from app.channels.models import WhatsAppChannel
from app.common.enums import (
    ChannelStatus,
    MessageDirection,
    MessageStatus,
    MessageType,
)
from app.database import SessionLocal
from app.delivery.models import MessageDelivery
from app.messages.models import Message
from app.users.models import TenantUser

from .base import PostgresIntegrationTestCase


class OperationalHealthTest(PostgresIntegrationTestCase):
    def _add_delivery(
        self,
        *,
        tenant_id,
        conversation_id,
        message_status: MessageStatus,
        delivery_status: str,
        created_at: datetime,
        completed_at: datetime | None = None,
    ) -> None:
        with SessionLocal() as db:
            message = Message(
                tenant_id=tenant_id,
                conversation_id=conversation_id,
                direction=MessageDirection.OUTGOING,
                message_type=MessageType.TEXT,
                status=message_status,
                body="Diagnóstico operacional",
                created_at=created_at,
            )
            db.add(message)
            db.flush()
            db.add(
                MessageDelivery(
                    tenant_id=tenant_id,
                    message_id=message.id,
                    status=delivery_status,
                    next_attempt_at=created_at,
                    completed_at=completed_at,
                )
            )
            db.commit()

    def test_health_is_admin_only_and_tenant_scoped(self) -> None:
        now = datetime.now(UTC)
        self._add_delivery(
            tenant_id=self.tenant_a.tenant_id,
            conversation_id=self.tenant_a.conversation_id,
            message_status=MessageStatus.PENDING,
            delivery_status="enqueued",
            created_at=now - timedelta(minutes=3),
        )
        self._add_delivery(
            tenant_id=self.tenant_a.tenant_id,
            conversation_id=self.tenant_a.conversation_id,
            message_status=MessageStatus.FAILED,
            delivery_status="failed",
            created_at=now - timedelta(minutes=5),
            completed_at=now - timedelta(minutes=4),
        )
        self._add_delivery(
            tenant_id=self.tenant_b.tenant_id,
            conversation_id=self.tenant_b.conversation_id,
            message_status=MessageStatus.FAILED,
            delivery_status="failed",
            created_at=now - timedelta(minutes=5),
            completed_at=now - timedelta(minutes=4),
        )
        with SessionLocal() as db:
            channel = db.scalar(
                select(WhatsAppChannel).where(
                    WhatsAppChannel.id == self.tenant_a.channel_id,
                    WhatsAppChannel.tenant_id == self.tenant_a.tenant_id,
                )
            )
            channel.status = ChannelStatus.DISCONNECTED
            db.commit()

        with patch(
            "app.operations.router._worker_health",
            return_value=(True, True, True),
        ):
            response = self.client.get(
                "/api/v1/operations/health",
                headers=self.headers_a,
            )

        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertEqual(payload["status"], "critical")
        self.assertEqual(payload["pending_deliveries"], 1)
        self.assertEqual(payload["delayed_deliveries"], 1)
        self.assertEqual(payload["failed_deliveries_24h"], 1)
        self.assertEqual(payload["connected_channels"], 0)
        self.assertEqual(payload["total_channels"], 1)
        self.assertEqual(
            {channel["id"] for channel in payload["channels"]},
            {str(self.tenant_a.channel_id)},
        )

        with SessionLocal() as db:
            membership = db.scalar(
                select(TenantUser).where(
                    TenantUser.tenant_id == self.tenant_a.tenant_id,
                    TenantUser.user_id == self.tenant_a.user_id,
                )
            )
            membership.role = "agent"
            db.commit()
        forbidden = self.client.get(
            "/api/v1/operations/health",
            headers=self.headers_a,
        )
        self.assertEqual(forbidden.status_code, 403, forbidden.text)

    def test_offline_delivery_worker_is_critical(self) -> None:
        with patch(
            "app.operations.router._worker_health",
            return_value=(True, False, True),
        ):
            response = self.client.get(
                "/api/v1/operations/health",
                headers=self.headers_a,
            )

        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertEqual(payload["status"], "critical")
        self.assertFalse(payload["delivery_worker_online"])
        self.assertTrue(
            any("Worker de entregas offline" in issue for issue in payload["issues"])
        )
