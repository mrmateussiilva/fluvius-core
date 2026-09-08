import asyncio
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import httpx
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.ai.models import ChannelAiConfig
from app.bots.configuration import end_bot_sessions
from app.bots.models import BotSession, BotTurn
from app.bots.service import execute_bot_turn
from app.channels.models import WhatsAppChannel
from app.common.enums import ChannelStatus, MessageStatus
from app.config import settings
from app.conversations.models import Conversation
from app.database import SessionLocal
from app.delivery.models import MessageDelivery
from app.messages.models import Message
from app.security import encrypt_secret

from .base import PostgresIntegrationTestCase


def response(*texts, session_id="external-session-1", finished=False):
    data = {
        "messages": [
            {
                "type": "text",
                "content": {
                    "type": "richText",
                    "richText": [
                        {"type": "p", "children": [{"text": body}]},
                    ],
                },
            }
            for body in texts
        ],
        "clientSideActions": [],
    }
    if session_id:
        data.update(sessionId=session_id, resultId="external-result-1")
    if not finished:
        data["input"] = {"type": "text input"}
    return httpx.Response(200, json=data)


class TypebotIntegrationTest(PostgresIntegrationTestCase):
    def setUp(self):
        super().setUp()
        self.addCleanup(patch.stopall)
        patch.object(settings, "typebot_base_url", "https://typebot.example").start()
        patch("app.realtime.manager.realtime_manager.broadcast", new_callable=AsyncMock).start()
        self.http = patch(
            "app.bots.typebot.client.httpx.AsyncClient.post",
            return_value=response("Olá", "Qual seu nome?"),
        ).start()
        self.llm = patch(
            "app.ai.service.call_llm",
            new_callable=AsyncMock,
            return_value=("IA nativa", False, None),
        ).start()
        self.gateway = patch(
            "app.delivery.service.get_provider", side_effect=AssertionError("bot must use outbox")
        ).start()
        self.url = f"/api/v1/channels/{self.tenant_a.channel_id}/typebot-config"

    def configure(self, **overrides):
        payload = {
            "engine": "typebot",
            "is_enabled": True,
            "public_id": "published-test-bot",
        } | overrides
        result = self.client.put(self.url, headers=self.headers_a, json=payload)
        self.assertEqual(result.status_code, 200, result.text)

    def incoming(self, body="Preciso consultar meu pedido", *, message_id=None, process=True):
        payload = {
            "event": "Message",
            "instanceName": "tenant-a",
            "instanceToken": settings.evolution_go_api_key,
            "data": {
                "Info": {
                    "ID": message_id or str(uuid4()),
                    "Sender": "5527993333333@s.whatsapp.net",
                    "Chat": "5527993333333@s.whatsapp.net",
                    "IsFromMe": False,
                    "IsGroup": False,
                    "PushName": "Cliente",
                    "Timestamp": "2026-09-06T10:00:00-03:00",
                    "Type": "text",
                },
                "Message": {"conversation": body},
            },
        }
        result = self.post_webhook(
            f"/api/v1/webhooks/whatsapp/evolution_go/{self.tenant_a.channel_id}",
            payload,
            process=process,
        )
        self.assertIn(result.status_code, (200, 202), result.text)
        return result

    def rows(self, model):
        with SessionLocal() as db:
            return list(
                db.scalars(
                    select(model)
                    .where(model.tenant_id == self.tenant_a.tenant_id)
                    .order_by(model.created_at, model.id)
                )
            )

    def bot_messages(self):
        return [m for m in self.rows(Message) if m.is_bot]

    def conversation(self):
        sessions = self.rows(BotSession)
        with SessionLocal() as db:
            return db.scalar(
                select(Conversation).where(
                    Conversation.tenant_id == self.tenant_a.tenant_id,
                    Conversation.id == sessions[-1].conversation_id,
                )
            )

    def toggle(self, active):
        result = self.client.post(
            f"/api/v1/conversations/{self.conversation().id}/toggle-bot",
            headers=self.headers_a,
            json={"is_bot_active": active},
        )
        self.assertEqual(result.status_code, 200, result.text)

    def test_configuration_is_tenant_scoped_admin_only_and_rejects_arbitrary_fields(self):
        self.configure()
        self.assertEqual(self.client.get(self.url, headers=self.headers_b).status_code, 404)
        self.assertEqual(
            self.client.put(
                self.url, headers=self.headers_b, json={"public_id": "other"}
            ).status_code,
            404,
        )
        other = self.client.get(
            f"/api/v1/channels/{self.tenant_b.channel_id}/typebot-config", headers=self.headers_b
        )
        self.assertIsNone(other.json()["public_id"])
        for extra in [{"tenant_id": str(self.tenant_b.tenant_id)}, {"base_url": "http://internal"}]:
            self.assertEqual(
                self.client.put(
                    self.url, headers=self.headers_a, json={"public_id": "bot"} | extra
                ).status_code,
                422,
            )
        from app.users.models import TenantUser

        with SessionLocal() as db:
            membership = db.scalar(
                select(TenantUser).where(
                    TenantUser.tenant_id == self.tenant_a.tenant_id,
                    TenantUser.user_id == self.tenant_a.user_id,
                )
            )
            membership.role = "agent"
            db.commit()
        self.assertEqual(self.client.get(self.url, headers=self.headers_a).status_code, 403)
        self.assertEqual(
            self.client.put(
                self.url, headers=self.headers_a, json={"public_id": "bot"}
            ).status_code,
            403,
        )

    def test_first_inbound_starts_session_and_next_continues_with_ordered_outbox(self):
        self.configure()
        self.incoming(message_id="first-inbound")
        session = self.rows(BotSession)[0]
        self.assertEqual(session.external_session_id, "external-session-1")
        self.assertEqual(session.result_id, "external-result-1")
        sent = self.http.call_args.kwargs["json"]
        self.assertEqual(sent["message"], {"type": "text", "text": "Preciso consultar meu pedido"})
        self.assertEqual(
            sent["prefilledVariables"]["fluvius_conversation_id"], str(session.conversation_id)
        )
        self.assertEqual(
            sent["prefilledVariables"]["fluvius_initial_message"], "Preciso consultar meu pedido"
        )
        self.assertEqual(
            set(sent["prefilledVariables"]),
            {
                "fluvius_conversation_id",
                "fluvius_contact_id",
                "fluvius_channel_id",
                "contact_name",
                "fluvius_initial_message",
            },
        )
        self.http.return_value = response("Prazer em conhecer você.", session_id=None)
        self.incoming("Mateus", message_id="second-inbound")
        self.assertEqual(
            self.http.call_args.args[0],
            "https://typebot.example/api/v1/sessions/external-session-1/continueChat",
        )
        self.assertEqual(self.http.call_args.kwargs["json"], {"message": "Mateus"})
        self.assertEqual(len(self.rows(BotSession)), 1)
        messages = self.bot_messages()
        self.assertEqual(
            [m.body for m in messages], ["Olá", "Qual seu nome?", "Prazer em conhecer você."]
        )
        self.assertTrue(
            all(
                m.status == MessageStatus.PENDING and m.provider_message_id is None
                for m in messages
            )
        )
        deliveries = self.rows(MessageDelivery)
        self.assertEqual({d.message_id for d in deliveries}, {m.id for m in messages})
        self.assertTrue(all(d.status == "queued" for d in deliveries))
        self.incoming("Mateus", message_id="second-inbound")
        asyncio.run(
            execute_bot_turn(
                tenant_id=self.tenant_a.tenant_id, conversation_id=session.conversation_id
            )
        )
        self.assertEqual(self.http.call_count, 2)
        self.gateway.assert_not_called()
        self.llm.assert_not_called()

    def test_other_tenant_cannot_execute_or_end_session(self):
        self.configure()
        self.incoming()
        session = self.rows(BotSession)[0]
        asyncio.run(
            execute_bot_turn(
                tenant_id=self.tenant_b.tenant_id, conversation_id=session.conversation_id
            )
        )
        with SessionLocal() as db:
            end_bot_sessions(db, self.tenant_b.tenant_id, session.conversation_id)
            db.commit()
        self.assertEqual(self.rows(BotSession)[0].status, "active")
        self.assertEqual(self.http.call_count, 1)

    def test_inactive_bot_never_calls_typebot_and_reactivation_creates_new_session(self):
        self.configure()
        self.incoming()
        self.toggle(False)
        self.incoming("Não chamar")
        self.assertEqual(self.http.call_count, 1)
        self.assertEqual(self.rows(BotSession)[0].status, "ended")
        self.toggle(True)
        self.http.return_value = response("Novo ciclo", session_id="external-session-2")
        self.incoming("Novo atendimento")
        self.assertTrue(self.http.call_args.args[0].endswith("/startChat"))
        self.assertEqual(
            [s.external_session_id for s in self.rows(BotSession)],
            ["external-session-1", "external-session-2"],
        )

    def test_human_takeover_during_http_discards_response(self):
        self.configure()

        async def takeover(*args, **kwargs):
            conversation = self.conversation()
            result = self.client.post(
                f"/api/v1/conversations/{conversation.id}/assign", headers=self.headers_a, json={}
            )
            self.assertEqual(result.status_code, 200, result.text)
            return response("NÃO ENVIAR")

        self.http.side_effect = takeover
        self.incoming()
        self.assertEqual(self.bot_messages(), [])
        self.assertEqual(self.rows(MessageDelivery), [])
        self.assertEqual(self.rows(BotTurn)[0].status, "discarded")
        self.assertEqual(self.rows(BotSession)[0].status, "ended")
        self.assertFalse(self.conversation().is_bot_active)
        self.incoming("Humano agora")
        self.assertEqual(self.http.call_count, 1)
        self.assertEqual(len(self.rows(BotSession)), 1)

    def test_close_and_reopen_starts_new_cycle(self):
        self.configure()
        self.incoming()
        cid = self.conversation().id
        self.assertEqual(
            self.client.post(
                f"/api/v1/conversations/{cid}/assign", headers=self.headers_a, json={}
            ).status_code,
            200,
        )
        self.assertEqual(
            self.client.post(
                f"/api/v1/conversations/{cid}/close", headers=self.headers_a
            ).status_code,
            200,
        )
        self.incoming("Reabertura")
        self.assertTrue(self.http.call_args.args[0].endswith("/startChat"))
        self.assertEqual(len(self.rows(BotSession)), 2)

    def test_timeout_hands_off_without_fake_message_or_retry(self):
        self.configure()
        self.http.side_effect = httpx.ReadTimeout("secret")
        self.incoming()
        self.assertFalse(self.conversation().is_bot_active)
        self.assertEqual(self.conversation().bot_handoff_reason, "typebot_unavailable")
        self.assertEqual(self.bot_messages(), [])
        self.assertEqual(self.rows(MessageDelivery), [])
        self.incoming("Outra mensagem")
        self.assertEqual(self.http.call_count, 1)

    def test_unsupported_bubble_does_not_break_worker(self):
        self.configure()
        self.http.return_value = httpx.Response(
            200,
            json={
                "sessionId": "s",
                "messages": [{"type": "image"}],
                "input": {"type": "text input"},
                "clientSideActions": [{"type": "scriptToExecute"}],
            },
        )
        self.incoming()
        self.assertEqual(self.rows(BotTurn)[0].status, "completed")
        self.assertEqual(self.bot_messages(), [])
        self.assertEqual(self.rows(BotSession)[0].external_session_id, "s")

    def test_native_ai_preserved_and_configuration_conflicts_rejected(self):
        ai_url = f"/api/v1/channels/{self.tenant_a.channel_id}/ai-config"
        result = self.client.put(
            ai_url, headers=self.headers_a, json={"is_enabled": True, "api_key": "test-key"}
        )
        self.assertEqual(result.status_code, 200, result.text)
        conflict = self.client.put(
            self.url, headers=self.headers_a, json={"is_enabled": True, "public_id": "bot"}
        )
        self.assertEqual(conflict.status_code, 409)
        self.incoming()
        self.llm.assert_awaited_once()
        self.http.assert_not_called()
        self.assertEqual(self.bot_messages()[0].body, "IA nativa")
        self.client.put(ai_url, headers=self.headers_a, json={"is_enabled": False})
        self.configure()
        self.assertEqual(
            self.client.put(ai_url, headers=self.headers_a, json={"is_enabled": True}).status_code,
            409,
        )
        self.incoming("Typebot agora")
        self.assertEqual(self.http.call_count, 1)
        self.assertEqual(self.llm.call_count, 1)

    def test_defensive_typebot_precedence_for_invalid_database_configuration(self):
        self.configure()
        with SessionLocal() as db:
            db.add(
                ChannelAiConfig(
                    tenant_id=self.tenant_a.tenant_id,
                    channel_id=self.tenant_a.channel_id,
                    is_enabled=True,
                    api_key_encrypted=encrypt_secret("test-key"),
                )
            )
            db.commit()
        self.incoming()
        self.llm.assert_not_called()
        self.assertEqual(self.http.call_count, 1)

    def test_interrupted_post_is_not_replayed(self):
        self.configure()
        with patch("app.providers.inbox_processor.execute_bot_turn", new_callable=AsyncMock):
            self.incoming()
        turn = self.rows(BotTurn)[0]
        with SessionLocal() as db:
            current = db.scalar(
                select(BotTurn).where(BotTurn.tenant_id == turn.tenant_id, BotTurn.id == turn.id)
            )
            current.status = "processing"
            db.commit()
        asyncio.run(
            execute_bot_turn(tenant_id=turn.tenant_id, conversation_id=self.conversation().id)
        )
        self.http.assert_not_called()
        self.assertEqual(self.conversation().bot_handoff_reason, "typebot_unavailable")

    def test_concurrent_workers_use_one_session_and_each_turn_once(self):
        self.configure()
        with patch("app.providers.inbox_processor.execute_bot_turn", new_callable=AsyncMock):
            self.incoming("Primeira")
            self.incoming("Segunda")
        cid = self.conversation().id
        entered = Event()
        release = Event()

        async def slow_reply(url, **kwargs):
            if url.endswith("startChat"):
                entered.set()
                self.assertTrue(await asyncio.to_thread(release.wait, 10))
            return response("Resposta")

        self.http.side_effect = slow_reply
        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(
                asyncio.run,
                execute_bot_turn(tenant_id=self.tenant_a.tenant_id, conversation_id=cid),
            )
            self.assertTrue(entered.wait(10))
            second = pool.submit(
                asyncio.run,
                execute_bot_turn(tenant_id=self.tenant_a.tenant_id, conversation_id=cid),
            )
            release.set()
            first.result(timeout=15)
            second.result(timeout=15)
        self.assertEqual(len(self.rows(BotSession)), 1)
        self.assertEqual(self.http.call_count, 2)
        self.assertTrue(self.http.call_args_list[0].args[0].endswith("startChat"))
        self.assertTrue(self.http.call_args_list[1].args[0].endswith("continueChat"))
        self.assertEqual([t.status for t in self.rows(BotTurn)], ["completed", "completed"])

    def test_database_rejects_two_active_sessions(self):
        self.configure()
        self.incoming()
        with SessionLocal() as db:
            db.add(
                BotSession(
                    tenant_id=self.tenant_a.tenant_id,
                    conversation_id=self.conversation().id,
                    public_id="other",
                )
            )
            with self.assertRaises(IntegrityError):
                db.commit()

    def test_forced_handoff_uses_existing_policy_and_outbox(self):
        self.configure()
        self.incoming("Quero falar com uma pessoa")
        self.http.assert_not_called()
        self.assertFalse(self.conversation().is_bot_active)
        self.assertEqual(
            self.conversation().bot_handoff_reason, "Cliente solicitou atendimento humano"
        )
        self.assertEqual(len(self.rows(MessageDelivery)), 1)
        self.assertEqual(self.rows(BotSession)[0].status, "ended")
        self.incoming("Ainda aguardando o atendente")
        self.assertEqual(len(self.rows(BotSession)), 1)
        self.http.assert_not_called()

    def test_finished_flow_ends_session_without_disabling_bot_or_handoff(self):
        self.configure()
        self.http.return_value = response("Concluído", finished=True)
        self.incoming()
        session = self.rows(BotSession)[0]
        self.assertEqual(session.status, "ended")
        self.assertIsNotNone(session.ended_at)
        self.assertTrue(self.conversation().is_bot_active)
        self.assertIsNone(self.conversation().bot_handoff_reason)
        self.assertIsNone(self.conversation().bot_handoff_at)
        self.assertEqual(self.bot_messages()[0].status, MessageStatus.PENDING)
        self.assertEqual(self.rows(MessageDelivery)[0].status, "queued")
        self.assertEqual(self.http.call_count, 1)

    def test_next_incoming_after_natural_completion_starts_new_session(self):
        self.configure()
        self.http.return_value = response("Concluído", finished=True)
        self.incoming()
        first = self.rows(BotSession)[0]
        self.http.return_value = response("Novo atendimento", session_id="external-session-2")
        self.incoming("Novo pedido")
        sessions = self.rows(BotSession)
        self.assertEqual(len(sessions), 2)
        self.assertEqual(sessions[0].id, first.id)
        self.assertEqual(sessions[0].status, "ended")
        self.assertNotEqual(sessions[1].id, first.id)
        self.assertEqual(sessions[1].status, "active")
        self.assertEqual(sessions[1].external_session_id, "external-session-2")
        self.assertEqual(sessions[1].conversation_id, first.conversation_id)
        self.assertTrue(
            all(call.args[0].endswith("/startChat") for call in self.http.call_args_list)
        )
        self.assertEqual(self.http.call_args.kwargs["json"]["message"]["text"], "Novo pedido")
        self.assertTrue(self.conversation().is_bot_active)
        self.assertIsNone(self.conversation().bot_handoff_at)

    def test_completion_on_continue_also_keeps_automation_enabled(self):
        self.configure()
        self.incoming()
        self.http.return_value = response("Concluído", session_id=None, finished=True)
        self.incoming("Resposta final")
        self.assertTrue(self.http.call_args.args[0].endswith("/continueChat"))
        self.assertEqual(self.rows(BotSession)[0].status, "ended")
        self.assertTrue(self.conversation().is_bot_active)
        self.assertIsNone(self.conversation().bot_handoff_reason)
        self.http.return_value = response("Novo ciclo", session_id="external-session-2")
        self.incoming("Novo pedido")
        self.assertTrue(self.http.call_args.args[0].endswith("/startChat"))
        self.assertEqual(len(self.rows(BotSession)), 2)

    def test_operator_after_natural_completion_disables_bot_and_prevents_new_session(self):
        self.configure()
        self.http.return_value = response("Concluído", finished=True)
        self.incoming()
        result = self.client.post(
            f"/api/v1/conversations/{self.conversation().id}/assign",
            headers=self.headers_a,
            json={},
        )
        self.assertEqual(result.status_code, 200, result.text)
        self.assertFalse(self.conversation().is_bot_active)
        self.incoming("Mensagem para o atendente")
        self.assertEqual(len(self.rows(BotSession)), 1)
        self.assertEqual(self.http.call_count, 1)

    def test_input_first_start_sends_initial_answer_and_keeps_incoming(self):
        # Mock the input-first contract, not the execution of a remote Typebot graph.
        self.configure()
        self.http.return_value = response("Pedido recebido", finished=True)
        self.incoming("Quero consultar meu pedido", message_id="input-first")
        self.assertEqual(self.http.call_count, 1)
        self.assertTrue(self.http.call_args.args[0].endswith("/startChat"))
        payload = self.http.call_args.kwargs["json"]
        self.assertEqual(payload["message"], {"type": "text", "text": "Quero consultar meu pedido"})
        self.assertNotIn("isOnlyRegistering", payload)
        stored = next(m for m in self.rows(Message) if m.provider_message_id == "input-first")
        self.assertEqual(stored.body, "Quero consultar meu pedido")
        self.assertEqual(self.bot_messages()[0].body, "Pedido recebido")

    def test_bubble_first_start_keeps_initial_variable_without_artificial_continue(self):
        self.configure()
        self.http.return_value = response("Bem-vindo! Qual seu nome?")
        self.incoming("Minha mensagem inicial", message_id="bubble-first")
        self.assertEqual(self.http.call_count, 1)
        payload = self.http.call_args.kwargs["json"]
        self.assertEqual(
            payload["prefilledVariables"]["fluvius_initial_message"], "Minha mensagem inicial"
        )
        self.assertNotIn("isOnlyRegistering", payload)
        stored = next(m for m in self.rows(Message) if m.provider_message_id == "bubble-first")
        self.assertEqual(stored.body, "Minha mensagem inicial")
        self.incoming("Mateus")
        self.assertEqual(self.http.call_count, 2)
        self.assertTrue(self.http.call_args.args[0].endswith("/continueChat"))
        self.assertEqual(self.http.call_args.kwargs["json"], {"message": "Mateus"})

    def test_channel_disconnect_during_http_discards_response(self):
        self.configure()

        async def disconnect(*args, **kwargs):
            with SessionLocal() as db:
                channel = db.scalar(
                    select(WhatsAppChannel).where(
                        WhatsAppChannel.tenant_id == self.tenant_a.tenant_id,
                        WhatsAppChannel.id == self.tenant_a.channel_id,
                    )
                )
                channel.status = ChannelStatus.DISCONNECTED
                db.commit()
            return response("NÃO ENVIAR")

        self.http.side_effect = disconnect
        self.incoming()
        self.assertEqual(self.bot_messages(), [])

    def test_toggle_off_on_during_http_invalidates_old_cycle(self):
        self.configure()

        async def change_cycle(*args, **kwargs):
            self.toggle(False)
            self.toggle(True)
            return response("NÃO ENVIAR")

        self.http.side_effect = change_cycle
        self.incoming()
        self.assertEqual(self.bot_messages(), [])
        self.assertEqual(self.rows(BotTurn)[0].status, "discarded")
        self.http.side_effect = None
        self.incoming("Nova execução")
        self.assertEqual(len(self.rows(BotSession)), 2)
        self.assertTrue(self.http.call_args.args[0].endswith("startChat"))

    def test_config_change_during_http_invalidates_response(self):
        self.configure()

        async def change_config(*args, **kwargs):
            self.configure(public_id="different-flow")
            return response("NÃO ENVIAR")

        self.http.side_effect = change_config
        self.incoming()
        self.assertEqual(self.bot_messages(), [])
        self.assertEqual(self.rows(BotTurn)[0].status, "discarded")
        self.http.side_effect = None
        self.incoming("Novo fluxo")
        self.assertIn("/typebots/different-flow/startChat", self.http.call_args.args[0])

    def test_http_500_and_malformed_response_handoff_without_outbox(self):
        self.configure()
        for invalid in (
            httpx.Response(500, text="secret"),
            httpx.Response(200, text="not json"),
            httpx.Response(200, json={"messages": []}),
        ):
            with self.subTest(invalid=invalid):
                self.http.return_value = invalid
                self.incoming()
                self.assertEqual(self.conversation().bot_handoff_reason, "typebot_unavailable")
                self.assertEqual(self.bot_messages(), [])
                self.assertEqual(self.rows(MessageDelivery), [])
                self.toggle(True)
        self.assertEqual(self.http.call_count, 3)

    def test_native_ai_discards_reply_when_human_takes_over_during_llm(self):
        ai_url = f"/api/v1/channels/{self.tenant_a.channel_id}/ai-config"
        self.client.put(
            ai_url, headers=self.headers_a, json={"is_enabled": True, "api_key": "test-key"}
        )

        async def takeover(**kwargs):
            with SessionLocal() as db:
                conversation = db.scalar(
                    select(Conversation).where(
                        Conversation.tenant_id == self.tenant_a.tenant_id,
                        Conversation.id != self.tenant_a.conversation_id,
                    )
                )
                cid = conversation.id
            result = self.client.post(
                f"/api/v1/conversations/{cid}/assign", headers=self.headers_a, json={}
            )
            self.assertEqual(result.status_code, 200, result.text)
            return "NÃO ENVIAR", False, None

        self.llm.side_effect = takeover
        self.incoming()
        self.assertEqual(self.bot_messages(), [])
        self.http.assert_not_called()

    def test_competing_administrative_enables_cannot_enable_both_engines(self):
        ai_url = f"/api/v1/channels/{self.tenant_a.channel_id}/ai-config"
        self.assertEqual(self.client.get(ai_url, headers=self.headers_a).status_code, 200)
        barrier = Barrier(2)

        def enable(url, payload):
            barrier.wait(timeout=10)
            return self.client.put(url, headers=self.headers_a, json=payload).status_code

        with ThreadPoolExecutor(max_workers=2) as pool:
            native = pool.submit(enable, ai_url, {"is_enabled": True})
            typebot = pool.submit(
                enable, self.url, {"is_enabled": True, "public_id": "published-bot"}
            )
            self.assertEqual(
                sorted([native.result(timeout=15), typebot.result(timeout=15)]), [200, 409]
            )

    def test_concurrent_inbound_workers_create_one_session(self):
        from app.providers.inbox_tasks import run_provider_event_inbox
        from app.providers.models import ProviderEventInbox

        self.configure()
        self.incoming("Primeira", process=False)
        self.incoming("Segunda", process=False)
        inboxes = self.rows(ProviderEventInbox)
        barrier = Barrier(2)

        def process(inbox):
            barrier.wait(timeout=10)
            return run_provider_event_inbox(str(inbox.id), str(inbox.tenant_id))

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(process, inbox) for inbox in inboxes]
            self.assertEqual([future.result(timeout=20) for future in futures], [True, True])
        self.assertEqual(len(self.rows(BotSession)), 1)
        self.assertEqual(self.http.call_count, 2)
        self.assertEqual(len(self.rows(BotTurn)), 2)
