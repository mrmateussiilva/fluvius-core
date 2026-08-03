import unittest
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from app.realtime.broker import dispatch_realtime_payload, emit_realtime_event


class RealtimeBrokerTest(unittest.IsolatedAsyncioTestCase):
    async def test_emits_an_event_through_redis_without_local_duplication(self) -> None:
        tenant_id = uuid4()
        data = {"id": str(uuid4()), "channel_id": str(uuid4())}
        with (
            patch("app.realtime.broker.settings.environment", "production"),
            patch(
                "app.realtime.broker._publish_realtime_payload",
                new=AsyncMock(return_value=True),
            ) as publish,
            patch(
                "app.realtime.broker.realtime_manager.broadcast_local",
                new=AsyncMock(),
            ) as broadcast_local,
        ):
            published = await emit_realtime_event(
                tenant_id,
                "message.created",
                data,
            )

        self.assertTrue(published)
        publish.assert_awaited_once_with(
            {
                "kind": "event",
                "tenant_id": str(tenant_id),
                "event": "message.created",
                "data": data,
            }
        )
        broadcast_local.assert_not_awaited()

    async def test_falls_back_to_local_delivery_without_redis_subscribers(self) -> None:
        tenant_id = uuid4()
        data = {"id": str(uuid4()), "channel_id": str(uuid4())}
        with (
            patch("app.realtime.broker.settings.environment", "production"),
            patch(
                "app.realtime.broker._publish_realtime_payload",
                new=AsyncMock(return_value=False),
            ),
            patch(
                "app.realtime.broker.realtime_manager.broadcast_local",
                new=AsyncMock(),
            ) as broadcast_local,
        ):
            published = await emit_realtime_event(
                tenant_id,
                "message.created",
                data,
            )

        self.assertFalse(published)
        broadcast_local.assert_awaited_once_with(
            tenant_id,
            "message.created",
            data,
        )

    async def test_dispatches_an_event_locally_without_republishing_it(self) -> None:
        tenant_id = uuid4()
        data = {
            "id": str(uuid4()),
            "conversation_id": str(uuid4()),
            "channel_id": str(uuid4()),
        }
        with (
            patch(
                "app.realtime.broker.realtime_manager.broadcast_local",
                new=AsyncMock(),
            ) as broadcast_local,
            patch(
                "app.realtime.broker.realtime_manager.broadcast",
                new=AsyncMock(),
            ) as broadcast,
        ):
            await dispatch_realtime_payload(
                {
                    "kind": "event",
                    "tenant_id": str(tenant_id),
                    "event": "message.created",
                    "data": data,
                }
            )

        broadcast_local.assert_awaited_once_with(
            tenant_id,
            "message.created",
            data,
        )
        broadcast.assert_not_awaited()

    async def test_dispatches_disconnect_commands_locally(self) -> None:
        tenant_id = uuid4()
        user_id = uuid4()
        with (
            patch(
                "app.realtime.broker.realtime_manager.disconnect_user_local",
                new=AsyncMock(),
            ) as disconnect_user,
            patch(
                "app.realtime.broker.realtime_manager.disconnect_tenant_local",
                new=AsyncMock(),
            ) as disconnect_tenant,
        ):
            await dispatch_realtime_payload(
                {
                    "kind": "disconnect_user",
                    "tenant_id": str(tenant_id),
                    "user_id": str(user_id),
                }
            )
            await dispatch_realtime_payload(
                {
                    "kind": "disconnect_tenant",
                    "tenant_id": str(tenant_id),
                }
            )

        disconnect_user.assert_awaited_once_with(tenant_id, user_id)
        disconnect_tenant.assert_awaited_once_with(tenant_id)


if __name__ == "__main__":
    unittest.main()
