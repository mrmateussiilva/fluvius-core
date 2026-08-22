import asyncio
import unittest
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import httpx
from redis.exceptions import RedisError

from app.common.enums import MessageStatus
from app.providers.base import IgnoredWebhookEvent
from app.providers.evolution_go import EvolutionGoProvider
from app.realtime.broker import emit_realtime_event
from app.realtime.manager import RealtimeManager


class BrokenWebSocket:
    """WebSocket simulation that fails on send."""

    def __init__(self, should_fail: bool = True) -> None:
        self.should_fail = should_fail
        self.accepted = False
        self.sent: list[dict] = []
        self.closed_with: int | None = None

    async def accept(self, subprotocol: str | None = None) -> None:
        self.accepted = True

    async def send_json(self, payload: dict) -> None:
        if self.should_fail:
            raise RuntimeError("WebSocket connection dropped by client")
        self.sent.append(payload)

    async def close(self, code: int) -> None:
        self.closed_with = code


class StabilityAndResilienceTest(unittest.IsolatedAsyncioTestCase):
    async def test_realtime_failing_client_isolation(self) -> None:
        """Broken/hanging client must not crash the broadcast or block healthy clients."""
        manager = RealtimeManager()
        tenant_id = uuid4()

        healthy_1 = BrokenWebSocket(should_fail=False)
        broken_client = BrokenWebSocket(should_fail=True)
        healthy_2 = BrokenWebSocket(should_fail=False)

        await manager.connect(tenant_id, healthy_1, user_id=uuid4())
        await manager.connect(tenant_id, broken_client, user_id=uuid4())
        await manager.connect(tenant_id, healthy_2, user_id=uuid4())

        self.assertEqual(len(manager._connections[tenant_id]), 3)

        # Broadcast event
        await manager.broadcast_local(
            tenant_id,
            "message.created",
            {"id": str(uuid4()), "body": "Resilience test"},
        )

        # Healthy clients must have received the event
        self.assertEqual(len(healthy_1.sent), 1)
        self.assertEqual(len(healthy_2.sent), 1)

        # Broken client must be automatically evicted from connections
        self.assertNotIn(broken_client, manager._connections[tenant_id])
        self.assertEqual(len(manager._connections[tenant_id]), 2)

    async def test_realtime_memory_leak_on_rapid_churn(self) -> None:
        """Rapid connect/disconnect cycles must cleanly purge memory with 0 orphaned entries."""
        manager = RealtimeManager()
        tenant_id = uuid4()

        sockets = [BrokenWebSocket(should_fail=False) for _ in range(500)]

        for ws in sockets:
            await manager.connect(tenant_id, ws, user_id=uuid4())

        self.assertEqual(len(manager._connections[tenant_id]), 500)

        # Disconnect all sockets
        for ws in sockets:
            manager.disconnect(tenant_id, ws)

        # Tenant entry must be fully removed from manager
        self.assertNotIn(tenant_id, manager._connections)

    def test_evolution_go_network_degradation_resilience(self) -> None:
        """Provider must categorize network errors safely and prevent duplicate sends."""
        # 1. Connect Timeout (Safe to retry)
        connect_err = httpx.ConnectTimeout("Connection timed out")
        res1 = EvolutionGoProvider._send_error_result(connect_err)
        self.assertFalse(res1.success)
        self.assertEqual(res1.status, MessageStatus.FAILED)
        self.assertTrue(res1.retryable)
        self.assertIn("temporariamente indisponível", res1.error)

        # 2. Read Timeout (Ambiguous - must NOT auto-retry to prevent duplicates)
        read_err = httpx.ReadTimeout("Read timed out")
        res2 = EvolutionGoProvider._send_error_result(read_err)
        self.assertFalse(res2.success)
        self.assertEqual(res2.status, MessageStatus.FAILED)
        self.assertFalse(res2.retryable)
        self.assertIn("incerta", res2.error)

        # 3. HTTP 401 Unauthorized (Credentials error - sanitized without leaking token)
        req = httpx.Request("POST", "http://evolution-go/message/sendText/main")
        resp_401 = httpx.Response(status_code=401, request=req)
        status_err_401 = httpx.HTTPStatusError("Unauthorized", request=req, response=resp_401)
        res3 = EvolutionGoProvider._send_error_result(status_err_401)
        self.assertFalse(res3.success)
        self.assertFalse(res3.retryable)
        self.assertIn("rejeitou o token", res3.error)
        self.assertNotIn("secret", res3.error)

        # 4. HTTP 429 Rate Limit (Retryable)
        resp_429 = httpx.Response(status_code=429, request=req)
        status_err_429 = httpx.HTTPStatusError("Rate limit", request=req, response=resp_429)
        res4 = EvolutionGoProvider._send_error_result(status_err_429)
        self.assertFalse(res4.success)
        self.assertTrue(res4.retryable)

    async def test_webhook_fuzzing_and_malformed_payload_stability(self) -> None:
        """Provider must gracefully handle malformed, truncated, or unexpected payloads."""
        provider = EvolutionGoProvider(
            base_url="http://evolution-go:8080",
            api_key="test-key",
        )

        malformed_inputs = [
            {},
            {"event": None},
            {"event": "UnknownCustomEvent", "data": {}},
            {"event": "Message", "data": None},
            {"event": "Message", "data": {}},
            {"event": "Message", "data": {"Info": None}},
            {"event": "Message", "data": {"Info": {}, "Message": None}},
            {"event": "Message", "data": {"Info": {"ID": 12345, "Sender": None}}},
            {"event": "Receipt", "data": None},
            {"event": "Receipt", "data": {"MessageIDs": None}},
            {"event": "Receipt", "data": {"MessageIDs": [], "Type": None}},
            {"event": "QRCODE", "data": None},
            {"event": "CONNECTION", "data": {"state": "invalid_status_string"}},
        ]

        for payload in malformed_inputs:
            # handle_webhook fuzz
            try:
                result = await provider.handle_webhook(payload)
                self.assertTrue(
                    result is None
                    or isinstance(result, IgnoredWebhookEvent)
                    or hasattr(result, "provider_message_id"),
                )
            except (ValueError, IgnoredWebhookEvent):
                # Expected handled domain validations
                pass
            except Exception as e:
                self.fail(f"handle_webhook raised unhandled error on {payload}: {e}")

            # handle_message_status fuzz
            try:
                status_result = provider.handle_message_status(payload)
                self.assertTrue(
                    status_result is None or hasattr(status_result, "status"),
                )
            except (ValueError, IgnoredWebhookEvent):
                pass
            except Exception as e:
                self.fail(f"handle_message_status raised unhandled error on {payload}: {e}")

    async def test_concurrent_multi_tenant_isolation_stability(self) -> None:
        """Events broadcast concurrently to multiple tenants must maintain strict isolation."""
        with patch("app.realtime.manager.settings.environment", "test"):
            manager = RealtimeManager()
            tenants = [uuid4() for _ in range(5)]
            clients_by_tenant: dict = {}

            # Connect 3 clients per tenant
            for t_id in tenants:
                clients_by_tenant[t_id] = [BrokenWebSocket(should_fail=False) for _ in range(3)]
                for client in clients_by_tenant[t_id]:
                    await manager.connect(t_id, client, user_id=uuid4())

            # Concurrently broadcast 20 events per tenant
            async def broadcast_tenant(t_id):
                for i in range(20):
                    await manager.broadcast_local(
                        t_id,
                        "message.created",
                        {"tenant_id": str(t_id), "seq": i},
                    )

            await asyncio.gather(*(broadcast_tenant(t_id) for t_id in tenants))

            # Verify each client received exactly 20 events and ALL events match tenant_id
            for t_id in tenants:
                for client in clients_by_tenant[t_id]:
                    self.assertEqual(len(client.sent), 20)
                    for event in client.sent:
                        self.assertEqual(event["data"]["tenant_id"], str(t_id))

    async def test_broker_redis_failure_fallback_stability(self) -> None:
        """RealtimeBroker falls back to local delivery if Redis fails."""
        tenant_id = uuid4()
        event_data = {"id": str(uuid4())}

        with (
            patch("app.realtime.broker.settings.environment", "production"),
            patch(
                "app.realtime.broker.AsyncRedis.from_url",
                side_effect=RedisError("Redis connection refused"),
            ),
            patch(
                "app.realtime.broker.realtime_manager.broadcast_local",
                new=AsyncMock(),
            ) as broadcast_local,
        ):
            published = await emit_realtime_event(
                tenant_id,
                "message.created",
                event_data,
            )

            self.assertFalse(published)
            broadcast_local.assert_awaited_once_with(
                tenant_id,
                "message.created",
                event_data,
            )


if __name__ == "__main__":
    unittest.main()
