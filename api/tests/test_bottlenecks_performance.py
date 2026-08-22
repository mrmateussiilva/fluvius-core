import time
import unittest
from datetime import UTC, datetime, timedelta
from unittest.mock import patch
from uuid import uuid4

from app.attachments.models import MessageAttachment
from app.common.enums import (
    MessageDirection,
    MessageStatus,
    MessageType,
)
from app.messages.models import Message
from app.messages.router import message_list_response
from app.providers.evolution_go import EvolutionGoProvider
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


def make_test_message(
    *,
    tenant_id,
    conversation_id,
    direction=MessageDirection.INCOMING,
    message_type=MessageType.TEXT,
    body="Texto",
    status=MessageStatus.READ,
    reply_to_message_id=None,
    created_at=None,
) -> Message:
    return Message(
        id=uuid4(),
        tenant_id=tenant_id,
        conversation_id=conversation_id,
        direction=direction,
        message_type=message_type,
        body=body,
        status=status,
        reply_to_message_id=reply_to_message_id,
        mentioned_phones=[],
        mentioned_jids=[],
        referenced_contacts=[],
        attempt_count=0,
        edit_content_unavailable=False,
        created_at=created_at or datetime.now(UTC),
    )


class BottlenecksPerformanceTest(unittest.IsolatedAsyncioTestCase):
    async def test_realtime_broadcast_throughput_and_fanout(self) -> None:
        """Benchmark high-volume event broadcast and channel filtering fanout."""
        with patch("app.realtime.manager.settings.environment", "test"):
            manager = RealtimeManager()
            tenant_id = uuid4()
            channel_a = uuid4()
            channel_b = uuid4()

            # Connect 50 clients: 10 admins, 20 channel_a agents, 20 channel_b agents
            admins = [FakeWebSocket() for _ in range(10)]
            agents_a = [FakeWebSocket() for _ in range(20)]
            agents_b = [FakeWebSocket() for _ in range(20)]

            for admin in admins:
                await manager.connect(tenant_id, admin, user_id=uuid4(), channel_ids=None)
            for agent in agents_a:
                await manager.connect(
                    tenant_id, agent, user_id=uuid4(), channel_ids=frozenset({channel_a})
                )
            for agent in agents_b:
                await manager.connect(
                    tenant_id, agent, user_id=uuid4(), channel_ids=frozenset({channel_b})
                )

            total_events = 1000
            start_time = time.perf_counter()

            # Broadcast 500 events on channel A and 500 on channel B
            for i in range(total_events):
                channel = channel_a if i % 2 == 0 else channel_b
                await manager.broadcast_local(
                    tenant_id,
                    "message.created",
                    {"id": str(uuid4()), "channel_id": str(channel), "index": i},
                )

            elapsed = time.perf_counter() - start_time
            throughput = total_events / elapsed

            # Admins must receive all 1000 events
            for admin in admins:
                self.assertEqual(len(admin.sent), 1000)
            # Channel A agents receive only 500 events
            for agent in agents_a:
                self.assertEqual(len(agent.sent), 500)
            # Channel B agents receive only 500 events
            for agent in agents_b:
                self.assertEqual(len(agent.sent), 500)

            # Assert fanout performance: throughput should exceed 1,000 events/sec in test env
            self.assertGreater(
                throughput,
                1000,
                f"Broadcast fanout too slow: {throughput:.2f} events/s (elapsed {elapsed:.4f}s)",
            )

    def test_message_list_serialization_bottleneck(self) -> None:
        """Benchmark batch serialization of 1,000 messages with attachments and replies."""
        tenant_id = uuid4()
        conversation_id = uuid4()

        messages = []
        attachments = []
        for i in range(1000):
            msg = make_test_message(
                tenant_id=tenant_id,
                conversation_id=conversation_id,
                body=f"Mensagem de benchmark #{i}",
                created_at=datetime.now(UTC) - timedelta(seconds=1000 - i),
            )
            messages.append(msg)
            if i % 5 == 0:
                att = MessageAttachment(
                    id=uuid4(),
                    tenant_id=tenant_id,
                    message_id=msg.id,
                    file_name=f"arquivo_{i}.pdf",
                    content_type="application/pdf",
                    size_bytes=1024 * (i + 1),
                    storage_key=f"tenants/{tenant_id}/arquivo_{i}.pdf",
                    public_url=f"http://api/attachments/{i}",
                )
                attachments.append(att)

        class MockBenchmarkDB:
            def scalars(self, stmt):
                stmt_str = str(stmt)
                if "attachments" in stmt_str:
                    return attachments
                if "message_contact_shares" in stmt_str:
                    return []
                if "messages" in stmt_str:
                    return []
                return []

            def scalar(self, stmt):
                return None

        start_time = time.perf_counter()
        responses = message_list_response(MockBenchmarkDB(), tenant_id, messages)
        elapsed = time.perf_counter() - start_time

        self.assertEqual(len(responses), 1000)
        # 1000 messages serialization must execute in < 0.5s
        self.assertLess(
            elapsed,
            0.5,
            f"Message list serialization bottleneck: took {elapsed:.4f}s for 1000 items",
        )

    async def test_evolution_webhook_handling_throughput(self) -> None:
        """Benchmark webhook event parsing and dispatch for 1,000 mixed payloads."""
        provider = EvolutionGoProvider(
            base_url="http://evolution-go:8080",
            api_key="test-api-key",
        )

        sample_message = {
            "event": "Message",
            "instanceId": "instance-id",
            "instanceName": "pessoal",
            "instanceToken": "instance-secret",
            "data": {
                "Info": {
                    "ID": "MESSAGE-123",
                    "Sender": "172434498003125@lid",
                    "SenderAlt": "5527999999999@s.whatsapp.net",
                    "RecipientAlt": "5527998888888@s.whatsapp.net",
                    "Chat": "172434498003125@lid",
                    "ChatName": "",
                    "IsFromMe": False,
                    "IsGroup": False,
                    "PushName": "Cliente Teste",
                    "Timestamp": "2026-07-21T20:48:18-03:00",
                    "Type": "text",
                },
                "Message": {"conversation": "Olá pelo WhatsApp"},
            },
        }

        sample_receipt = {
            "event": "Receipt",
            "state": "Delivered",
            "instanceId": "instance-id",
            "instanceName": "pessoal",
            "instanceToken": "instance-secret",
            "data": {
                "Chat": "5527999999999@s.whatsapp.net",
                "MessageIDs": ["OUTGOING-456"],
                "Timestamp": "2026-07-21T21:10:00-03:00",
                "Type": "delivered",
            },
        }

        start_time = time.perf_counter()
        count = 1000
        for i in range(count):
            if i % 2 == 0:
                result = await provider.handle_webhook(sample_message)
                self.assertIsNotNone(result)
            else:
                status_result = provider.handle_message_status(sample_receipt)
                self.assertEqual(status_result.status, MessageStatus.DELIVERED)

        elapsed = time.perf_counter() - start_time
        throughput = count / elapsed

        self.assertGreater(
            throughput,
            1000,
            f"Webhook handling bottleneck: {throughput:.2f} payloads/s (took {elapsed:.4f}s)",
        )


if __name__ == "__main__":
    unittest.main()
