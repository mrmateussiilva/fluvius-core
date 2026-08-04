from datetime import UTC, datetime, timedelta
from unittest.mock import patch

from sqlalchemy import select

from app.channels.models import WhatsAppChannel
from app.common.audit_models import AuditLog
from app.common.enums import (
    ChannelStatus,
    MessageDirection,
    MessageStatus,
    MessageType,
)
from app.database import SessionLocal
from app.delivery.models import MessageDelivery
from app.messages.models import Message
from app.providers.evolution_go import EvolutionGoProvider
from app.providers.models import ProviderEvent
from app.providers.pending_events import (
    PENDING_INCOMING_MESSAGE_ERROR,
    PENDING_RECEIPT_ERROR,
)
from app.providers.reconcile import WebhookReconcileRuntime
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

    def test_health_surfaces_pending_webhooks_tenant_scoped(self) -> None:
        now = datetime.now(UTC)
        with SessionLocal() as db:
            db.add(
                ProviderEvent(
                    tenant_id=self.tenant_a.tenant_id,
                    channel_id=self.tenant_a.channel_id,
                    provider="evolution_go",
                    event_type="Receipt",
                    provider_event_id="receipt-pending-a",
                    payload={"event": "Receipt"},
                    processed=False,
                    processing_error=PENDING_RECEIPT_ERROR,
                    created_at=now - timedelta(minutes=20),
                )
            )
            db.add(
                ProviderEvent(
                    tenant_id=self.tenant_a.tenant_id,
                    channel_id=self.tenant_a.channel_id,
                    provider="evolution_go",
                    event_type="Message",
                    provider_event_id="message-failed-a",
                    payload={"event": "Message"},
                    processed=False,
                    processing_error="Payload inválido do gateway",
                )
            )
            db.add(
                ProviderEvent(
                    tenant_id=self.tenant_b.tenant_id,
                    channel_id=self.tenant_b.channel_id,
                    provider="evolution_go",
                    event_type="Receipt",
                    provider_event_id="receipt-pending-b",
                    payload={"event": "Receipt"},
                    processed=False,
                    processing_error=PENDING_RECEIPT_ERROR,
                )
            )
            db.commit()

        with patch(
            "app.operations.router._worker_health",
            return_value=(True, True, True),
        ), patch(
            "app.operations.router.get_webhook_reconcile_runtime",
            return_value=WebhookReconcileRuntime(active=True, heartbeat_at=now),
        ):
            response = self.client.get(
                "/api/v1/operations/health",
                headers=self.headers_a,
            )

        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertEqual(payload["pending_provider_events"], 1)
        self.assertEqual(payload["failed_provider_events"], 1)
        self.assertEqual(payload["status"], "attention")
        self.assertTrue(
            any("webhook aguardando reconciliação" in issue for issue in payload["issues"])
        )
        channel = next(
            item
            for item in payload["channels"]
            if item["id"] == str(self.tenant_a.channel_id)
        )
        self.assertEqual(channel["pending_events"], 1)
        self.assertEqual(channel["failed_events"], 1)

    def test_stale_pending_webhooks_are_critical_when_reconciler_is_inactive(self) -> None:
        now = datetime.now(UTC)
        with SessionLocal() as db:
            db.add(
                ProviderEvent(
                    tenant_id=self.tenant_a.tenant_id,
                    channel_id=self.tenant_a.channel_id,
                    provider="evolution_go",
                    event_type="Receipt",
                    provider_event_id="receipt-pending-inactive-reconciler",
                    payload={"event": "Receipt"},
                    processed=False,
                    processing_error=PENDING_RECEIPT_ERROR,
                    created_at=now - timedelta(minutes=20),
                )
            )
            db.commit()

        with patch(
            "app.operations.router._worker_health",
            return_value=(True, True, True),
        ), patch(
            "app.operations.router.get_webhook_reconcile_runtime",
            return_value=WebhookReconcileRuntime(active=False),
        ):
            response = self.client.get(
                "/api/v1/operations/health",
                headers=self.headers_a,
            )

        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertEqual(payload["status"], "critical")
        self.assertTrue(
            any("sem heartbeat recente" in issue for issue in payload["issues"])
        )

    def test_health_surfaces_webhook_reconcile_runtime(self) -> None:
        now = datetime.now(UTC)
        with patch(
            "app.operations.router._worker_health",
            return_value=(True, True, True),
        ), patch(
            "app.operations.router.get_webhook_reconcile_runtime",
            return_value=WebhookReconcileRuntime(
                active=True,
                heartbeat_at=now,
                last_started_at=now,
                last_finished_at=now,
                last_scanned_channels=2,
                last_checked_events=10,
                last_resolved_events=7,
            ),
        ):
            response = self.client.get(
                "/api/v1/operations/health",
                headers=self.headers_a,
            )

        self.assertEqual(response.status_code, 200, response.text)
        runtime = response.json()["webhook_reconcile"]
        self.assertTrue(runtime["active"])
        self.assertEqual(runtime["last_scanned_channels"], 2)
        self.assertEqual(runtime["last_checked_events"], 10)
        self.assertEqual(runtime["last_resolved_events"], 7)

    def test_reconcile_webhooks_endpoint_is_tenant_scoped(self) -> None:
        with SessionLocal() as db:
            message = Message(
                tenant_id=self.tenant_a.tenant_id,
                conversation_id=self.tenant_a.conversation_id,
                direction=MessageDirection.OUTGOING,
                message_type=MessageType.TEXT,
                status=MessageStatus.SENT,
                body="Mensagem com recibo pendente",
                provider_message_id="ops-reconcile-outgoing-1",
            )
            event_a = ProviderEvent(
                tenant_id=self.tenant_a.tenant_id,
                channel_id=self.tenant_a.channel_id,
                provider="evolution_go",
                event_type="Receipt",
                provider_event_id="ops-reconcile-receipt-a",
                payload={
                    "event": "Receipt",
                    "state": "Delivered",
                    "data": {
                        "MessageIDs": ["ops-reconcile-outgoing-1"],
                        "Timestamp": "2026-07-27T00:00:00-03:00",
                        "Type": "delivered",
                    },
                },
                processed=False,
                processing_error=PENDING_RECEIPT_ERROR,
            )
            event_b = ProviderEvent(
                tenant_id=self.tenant_b.tenant_id,
                channel_id=self.tenant_b.channel_id,
                provider="evolution_go",
                event_type="Receipt",
                provider_event_id="ops-reconcile-receipt-b",
                payload={
                    "event": "Receipt",
                    "state": "Delivered",
                    "data": {"MessageIDs": ["tenant-b-message"]},
                },
                processed=False,
                processing_error=PENDING_RECEIPT_ERROR,
            )
            db.add_all([message, event_a, event_b])
            db.commit()
            message_id = message.id
            event_a_id = event_a.id
            event_b_id = event_b.id

        provider = EvolutionGoProvider(api_key="test-token")
        with patch(
            "app.providers.reconcile.claim_evolution_credential",
        ), patch(
            "app.providers.reconcile.get_provider",
            return_value=provider,
        ):
            response = self.client.post(
                "/api/v1/operations/webhooks/reconcile",
                headers=self.headers_a,
                json={"channel_id": str(self.tenant_a.channel_id)},
            )

        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertEqual(payload["scanned_channels"], 1)
        self.assertEqual(payload["checked_events"], 1)
        self.assertEqual(payload["resolved_events"], 1)
        self.assertEqual(payload["remaining_pending_events"], 0)

        cross_tenant = self.client.post(
            "/api/v1/operations/webhooks/reconcile",
            headers=self.headers_a,
            json={"channel_id": str(self.tenant_b.channel_id)},
        )
        self.assertEqual(cross_tenant.status_code, 404)

        with SessionLocal() as db:
            message = db.scalar(
                select(Message).where(
                    Message.id == message_id,
                    Message.tenant_id == self.tenant_a.tenant_id,
                )
            )
            event_a = db.scalar(
                select(ProviderEvent).where(
                    ProviderEvent.id == event_a_id,
                    ProviderEvent.tenant_id == self.tenant_a.tenant_id,
                )
            )
            event_b = db.scalar(
                select(ProviderEvent).where(
                    ProviderEvent.id == event_b_id,
                    ProviderEvent.tenant_id == self.tenant_b.tenant_id,
                )
            )
            audit = db.scalar(
                select(AuditLog).where(
                    AuditLog.tenant_id == self.tenant_a.tenant_id,
                    AuditLog.action == "operations.webhooks.reconciled",
                )
            )
            self.assertEqual(message.status, MessageStatus.DELIVERED)
            self.assertTrue(event_a.processed)
            self.assertIsNone(event_a.processing_error)
            self.assertFalse(event_b.processed)
            self.assertIsNotNone(audit)

    def test_reconcile_webhooks_recovers_a_persisted_incoming_message(self) -> None:
        provider_message_id = "ops-reconcile-incoming-1"
        customer_phone = "5527999443322"
        event_payload = {
            "event": "Message",
            "instanceId": "integration-instance",
            "instanceName": "tenant-a",
            "data": {
                "Info": {
                    "ID": provider_message_id,
                    "Sender": f"{customer_phone}@s.whatsapp.net",
                    "Chat": f"{customer_phone}@s.whatsapp.net",
                    "IsFromMe": False,
                    "IsGroup": False,
                    "PushName": "Cliente Recuperado",
                    "Timestamp": "2026-08-04T08:00:00-03:00",
                    "Type": "text",
                },
                "Message": {"conversation": "Mensagem recuperada"},
            },
        }
        with SessionLocal() as db:
            event = ProviderEvent(
                tenant_id=self.tenant_a.tenant_id,
                channel_id=self.tenant_a.channel_id,
                provider="evolution_go",
                event_type="Message",
                provider_event_id=f"message:{provider_message_id}",
                payload=event_payload,
                processed=False,
                processing_error=PENDING_INCOMING_MESSAGE_ERROR,
            )
            db.add(event)
            db.commit()
            event_id = event.id

        provider = EvolutionGoProvider(api_key="test-token")
        with (
            patch("app.providers.reconcile.claim_evolution_credential"),
            patch("app.providers.reconcile.get_provider", return_value=provider),
            patch("app.providers.webhook_router.claim_evolution_credential"),
            patch("app.providers.webhook_router.get_provider", return_value=provider),
        ):
            response = self.client.post(
                "/api/v1/operations/webhooks/reconcile",
                headers=self.headers_a,
                json={"channel_id": str(self.tenant_a.channel_id)},
            )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["checked_events"], 1)
        self.assertEqual(response.json()["resolved_events"], 1)
        self.assertEqual(response.json()["remaining_pending_events"], 0)

        with SessionLocal() as db:
            event = db.scalar(
                select(ProviderEvent).where(
                    ProviderEvent.id == event_id,
                    ProviderEvent.tenant_id == self.tenant_a.tenant_id,
                )
            )
            message = db.scalar(
                select(Message).where(
                    Message.tenant_id == self.tenant_a.tenant_id,
                    Message.provider_message_id == provider_message_id,
                )
            )

        self.assertTrue(event.processed)
        self.assertIsNone(event.processing_error)
        self.assertIsNotNone(message)
        self.assertEqual(message.body, "Mensagem recuperada")
