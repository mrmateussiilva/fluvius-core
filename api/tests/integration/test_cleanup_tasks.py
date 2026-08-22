from datetime import UTC, datetime, timedelta
from uuid import uuid4

from app.database import SessionLocal
from app.providers.cleanup_tasks import cleanup_old_processed_events
from app.providers.models import ProviderEvent, ProviderEventInbox
from app.tenants.models import Tenant

from .base import PostgresIntegrationTestCase


class CleanupTasksTest(PostgresIntegrationTestCase):
    def test_cleanup_removes_only_old_processed_events(self) -> None:
        with SessionLocal() as db:
            tenant = Tenant(
                id=uuid4(),
                name="Test Tenant Cleanup",
                slug=f"cleanup-{uuid4().hex[:8]}",
            )
            db.add(tenant)
            db.flush()

            old_time = datetime.now(UTC) - timedelta(days=40)
            recent_time = datetime.now(UTC) - timedelta(days=5)

            # Old processed event (should be deleted)
            old_event = ProviderEvent(
                id=uuid4(),
                tenant_id=tenant.id,
                channel_id=uuid4(),
                provider="evolution_go",
                event_type="Message",
                processed=True,
                created_at=old_time,
                payload={},
            )
            db.add(old_event)

            # Recent processed event (should stay)
            recent_event = ProviderEvent(
                id=uuid4(),
                tenant_id=tenant.id,
                channel_id=uuid4(),
                provider="evolution_go",
                event_type="Message",
                processed=True,
                created_at=recent_time,
                payload={},
            )
            db.add(recent_event)

            # Old completed inbox (should be deleted)
            old_inbox = ProviderEventInbox(
                id=uuid4(),
                tenant_id=tenant.id,
                provider_event_id=old_event.id,
                status="completed",
                completed_at=old_time,
                normalized_kind="message",
                normalized_payload={},
            )
            db.add(old_inbox)

            # Recent completed inbox (should stay)
            recent_inbox = ProviderEventInbox(
                id=uuid4(),
                tenant_id=tenant.id,
                provider_event_id=recent_event.id,
                status="completed",
                completed_at=recent_time,
                normalized_kind="message",
                normalized_payload={},
            )
            db.add(recent_inbox)
            db.commit()

            deleted = cleanup_old_processed_events(retention_days=30)
            self.assertGreaterEqual(deleted, 2)

            remaining_old_event = db.get(ProviderEvent, old_event.id)
            remaining_recent_event = db.get(ProviderEvent, recent_event.id)
            remaining_old_inbox = db.get(ProviderEventInbox, old_inbox.id)
            remaining_recent_inbox = db.get(ProviderEventInbox, recent_inbox.id)

            self.assertIsNone(remaining_old_event)
            self.assertIsNotNone(remaining_recent_event)
            self.assertIsNone(remaining_old_inbox)
            self.assertIsNotNone(remaining_recent_inbox)

            db.delete(remaining_recent_inbox)
            db.delete(remaining_recent_event)
            db.delete(tenant)
            db.commit()
