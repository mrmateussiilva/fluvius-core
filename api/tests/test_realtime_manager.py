import unittest
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from app.realtime.manager import RealtimeManager


class FakeWebSocket:
    def __init__(self) -> None:
        self.accepted = False
        self.sent: list[dict] = []
        self.closed_with: int | None = None

    async def accept(self, subprotocol: str | None = None) -> None:
        self.accepted = True

    async def send_json(self, payload: dict) -> None:
        self.sent.append(payload)

    async def close(self, code: int) -> None:
        self.closed_with = code


class RealtimeManagerTest(unittest.IsolatedAsyncioTestCase):
    async def test_routes_broadcast_through_the_realtime_broker(self) -> None:
        manager = RealtimeManager()
        tenant_id = uuid4()
        data = {"id": str(uuid4()), "channel_id": str(uuid4())}

        with (
            patch("app.realtime.manager.settings.environment", "production"),
            patch(
                "app.realtime.broker.emit_realtime_event",
                new=AsyncMock(return_value=True),
            ) as emit,
        ):
            await manager.broadcast(tenant_id, "message.created", data)

        emit.assert_awaited_once_with(tenant_id, "message.created", data)

    async def test_broadcasts_only_to_users_authorized_for_the_channel(self) -> None:
        with patch("app.realtime.manager.settings.environment", "test"):
            manager = RealtimeManager()
            tenant_id = uuid4()
            channel_a = uuid4()
            channel_b = uuid4()
            admin_user_id = uuid4()
            agent_a_user_id = uuid4()
            agent_b_user_id = uuid4()
            admin = FakeWebSocket()
            agent_a = FakeWebSocket()
            agent_b = FakeWebSocket()

            await manager.connect(
                tenant_id,
                admin,
                user_id=admin_user_id,
                channel_ids=None,
            )
            await manager.connect(
                tenant_id,
                agent_a,
                user_id=agent_a_user_id,
                channel_ids=frozenset({channel_a}),
            )
            await manager.connect(
                tenant_id,
                agent_b,
                user_id=agent_b_user_id,
                channel_ids=frozenset({channel_b}),
            )

            await manager.broadcast(
                tenant_id,
                "conversation.updated",
                {"id": str(uuid4()), "channel_id": str(channel_a)},
            )

            self.assertEqual(len(admin.sent), 1)
            self.assertEqual(len(agent_a.sent), 1)
            self.assertEqual(agent_b.sent, [])

            await manager.broadcast(
                tenant_id,
                "tenant.internal",
                {"id": str(uuid4())},
            )

            self.assertEqual(len(admin.sent), 2)
            self.assertEqual(len(agent_a.sent), 1)
            self.assertEqual(agent_b.sent, [])

            await manager.disconnect_user(tenant_id, agent_a_user_id)
            self.assertEqual(agent_a.closed_with, 1008)
            self.assertNotIn(agent_a, manager._connections[tenant_id])

            await manager.disconnect_tenant(tenant_id)
            self.assertEqual(admin.closed_with, 1008)
            self.assertEqual(agent_b.closed_with, 1008)
            self.assertNotIn(tenant_id, manager._connections)
