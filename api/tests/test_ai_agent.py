import unittest
from datetime import UTC, datetime
from unittest.mock import ANY, AsyncMock, MagicMock, patch
from uuid import uuid4

import httpx

from app.ai.models import ChannelAiConfig
from app.ai.service import (
    call_llm,
    detect_forced_handoff,
    execute_ai_turn,
)
from app.channels.models import WhatsAppChannel
from app.common.enums import (
    ChannelProvider,
    ChannelStatus,
    ContactKind,
    ConversationStatus,
    MessageDirection,
    MessageType,
)
from app.contacts.models import Contact
from app.conversations.models import Conversation
from app.delivery.models import MessageDelivery
from app.messages.models import Message
from app.security import decrypt_secret, encrypt_secret


class AiAgentUnitTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.tenant_id = uuid4()
        self.channel_id = uuid4()
        self.conversation_id = uuid4()
        self.contact_id = uuid4()
        self.user_id = uuid4()

    def test_encryption_roundtrip(self) -> None:
        plain = "sk-super-secret-key-12345"
        encrypted = encrypt_secret(plain)
        self.assertNotEqual(plain, encrypted)
        self.assertEqual(decrypt_secret(encrypted), plain)

    async def test_call_llm_text_reply(self) -> None:
        mock_response = {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": "Olá! Como posso ajudar você hoje?",
                    }
                }
            ]
        }

        with patch("httpx.AsyncClient.post") as mock_post:
            mock_post.return_value = httpx.Response(200, json=mock_response)

            reply, handoff_triggered, reason = await call_llm(
                provider="openai",
                model_name="gpt-4o-mini",
                api_key="sk-test",
                system_prompt="Você é um assistente.",
                conversation_messages=[{"role": "user", "content": "Olá"}],
            )

            self.assertEqual(reply, "Olá! Como posso ajudar você hoje?")
            self.assertFalse(handoff_triggered)
            self.assertIsNone(reason)
            system_message = mock_post.call_args.kwargs["json"]["messages"][0]["content"]
            self.assertIn("Política de triagem obrigatória", system_message)
            self.assertIn("ferramenta 'solicitar_atendente_humano'", system_message)

    async def test_call_llm_receives_configured_agent_identity(self) -> None:
        mock_response = {
            "choices": [{"message": {"role": "assistant", "content": "Olá!"}}]
        }

        from app.ai.service import _build_agent_system_prompt

        with patch("httpx.AsyncClient.post") as mock_post:
            mock_post.return_value = httpx.Response(200, json=mock_response)

            await call_llm(
                provider="openai",
                model_name="gpt-4o-mini",
                api_key="sk-test",
                system_prompt=_build_agent_system_prompt("Você atende clientes.", "Sofia"),
                conversation_messages=[{"role": "user", "content": "Oi Sofia"}],
            )

            system_message = mock_post.call_args.kwargs["json"]["messages"][0]["content"]
            self.assertIn("seu nome é Sofia", system_message)
            self.assertIn("A menção ao nome não é obrigatória", system_message)

    async def test_call_llm_handoff_tool_call(self) -> None:
        mock_response = {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            {
                                "id": "call_123",
                                "type": "function",
                                "function": {
                                    "name": "solicitar_atendente_humano",
                                    "arguments": '{"motivo": "Cliente quer falar com atendente humano", "mensagem_ao_cliente": "Transferindo para nossa equipe humana."}',
                                },
                            }
                        ],
                    }
                }
            ]
        }

        with patch("httpx.AsyncClient.post") as mock_post:
            mock_post.return_value = httpx.Response(200, json=mock_response)

            reply, handoff_triggered, reason = await call_llm(
                provider="openai",
                model_name="gpt-4o-mini",
                api_key="sk-test",
                system_prompt="Você é um assistente.",
                conversation_messages=[{"role": "user", "content": "Quero falar com um humano"}],
            )

            self.assertEqual(reply, "Transferindo para nossa equipe humana.")
            self.assertTrue(handoff_triggered)
            self.assertEqual(reason, "Cliente quer falar com atendente humano")

    def test_detect_forced_handoff_normalizes_accents(self) -> None:
        self.assertEqual(
            detect_forced_handoff("Estou insatisfeito e quero falar com uma pessoa."),
            "Cliente solicitou atendimento humano",
        )
        self.assertEqual(
            detect_forced_handoff("Vou procurar o PROCON."),
            "Cliente registrou uma reclamação",
        )
        self.assertIsNone(detect_forced_handoff("Olá, preciso consultar meu pedido."))

    async def test_ai_turn_forced_handoff_skips_llm_and_deactivates_bot(self) -> None:
        conv = Conversation(
            id=self.conversation_id,
            tenant_id=self.tenant_id,
            channel_id=self.channel_id,
            contact_id=self.contact_id,
            status=ConversationStatus.NEW,
            is_bot_active=True,
        )
        channel = WhatsAppChannel(
            id=self.channel_id,
            tenant_id=self.tenant_id,
            name="Principal",
            phone_number="5511999999999",
            provider=ChannelProvider.EVOLUTION_GO,
            status=ChannelStatus.CONNECTED,
        )
        config = ChannelAiConfig(
            id=uuid4(),
            tenant_id=self.tenant_id,
            channel_id=self.channel_id,
            is_enabled=True,
            api_key_encrypted=encrypt_secret("sk-test-123"),
            bot_name="IA Assistente",
        )
        contact = Contact(
            id=self.contact_id,
            tenant_id=self.tenant_id,
            kind=ContactKind.DIRECT,
            phone_number="5511888888888",
        )
        incoming = Message(
            id=uuid4(),
            tenant_id=self.tenant_id,
            conversation_id=self.conversation_id,
            direction=MessageDirection.INCOMING,
            message_type=MessageType.TEXT,
            body="Quero falar com um atendente humano, por favor.",
        )
        delivery = MessageDelivery(
            id=uuid4(),
            tenant_id=self.tenant_id,
            message_id=uuid4(),
        )

        mock_db = MagicMock()
        mock_db.scalar.side_effect = [conv, channel, config, contact, conv]
        mock_db.scalars.return_value = [incoming]
        mock_db.refresh.side_effect = lambda item: setattr(item, "created_at", datetime.now(UTC))

        with (
            patch("app.ai.service.call_llm", new_callable=AsyncMock) as mock_llm,
            patch("app.ai.service.create_delivery", return_value=delivery),
            patch("app.ai.service.dispatch_delivery"),
            patch("app.ai.service.realtime_manager.broadcast", new_callable=AsyncMock),
        ):
            await execute_ai_turn(mock_db, self.tenant_id, self.conversation_id)

        mock_llm.assert_not_awaited()
        self.assertFalse(conv.is_bot_active)
        self.assertEqual(conv.bot_handoff_reason, "Cliente solicitou atendimento humano")
        created_message = next(
            item
            for item in mock_db.add.call_args_list[0].args
            if isinstance(item, Message)
        )
        self.assertEqual(
            created_message.body,
            "Entendido! Estou transferindo seu atendimento para a nossa equipe humana. "
            "Um de nossos atendentes irá te responder em instantes.",
        )

    async def test_ai_turn_skips_when_assigned_to_human(self) -> None:
        """Invariant: Bot never responds if conversation has an assigned human operator."""
        conv = Conversation(
            id=self.conversation_id,
            tenant_id=self.tenant_id,
            channel_id=self.channel_id,
            contact_id=self.contact_id,
            status=ConversationStatus.OPEN,
            assigned_user_id=self.user_id,
            is_bot_active=True,
        )

        mock_db = MagicMock()
        mock_db.scalar.return_value = conv

        with patch("app.ai.service.call_llm") as mock_llm:
            await execute_ai_turn(mock_db, self.tenant_id, self.conversation_id)
            mock_llm.assert_not_called()

    async def test_ai_turn_creates_and_dispatches_tenant_scoped_delivery(self) -> None:
        conv = Conversation(
            id=self.conversation_id,
            tenant_id=self.tenant_id,
            channel_id=self.channel_id,
            contact_id=self.contact_id,
            status=ConversationStatus.NEW,
            is_bot_active=True,
        )
        channel = WhatsAppChannel(
            id=self.channel_id,
            tenant_id=self.tenant_id,
            name="Principal",
            phone_number="5511999999999",
            provider=ChannelProvider.EVOLUTION_GO,
            status=ChannelStatus.CONNECTED,
        )
        config = ChannelAiConfig(
            id=uuid4(),
            tenant_id=self.tenant_id,
            channel_id=self.channel_id,
            is_enabled=True,
            provider="openai",
            model_name="gpt-4o-mini",
            api_key_encrypted=encrypt_secret("sk-test-123"),
            bot_name="IA Assistente",
            system_prompt="Você é um assistente.",
            handoff_prompt="Transfira quando necessário.",
            temperature=0.3,
            max_tokens=500,
        )
        contact = Contact(
            id=self.contact_id,
            tenant_id=self.tenant_id,
            kind=ContactKind.DIRECT,
            phone_number="5511888888888",
        )
        incoming = Message(
            id=uuid4(),
            tenant_id=self.tenant_id,
            conversation_id=self.conversation_id,
            direction=MessageDirection.INCOMING,
            message_type=MessageType.TEXT,
            body="Olá",
        )
        delivery = MessageDelivery(
            id=uuid4(),
            tenant_id=self.tenant_id,
            message_id=uuid4(),
        )

        mock_db = MagicMock()
        mock_db.scalar.side_effect = [conv, channel, config, contact, conv]
        mock_db.scalars.return_value = [incoming]
        mock_db.refresh.side_effect = lambda item: setattr(item, "created_at", datetime.now(UTC))

        with (
            patch("app.ai.service.call_llm", return_value=("Olá!", False, None)),
            patch("app.ai.service.create_delivery", return_value=delivery) as create_delivery_mock,
            patch("app.ai.service.dispatch_delivery") as dispatch_delivery_mock,
            patch(
                "app.ai.service.realtime_manager.broadcast",
                new_callable=AsyncMock,
            ) as realtime_broadcast_mock,
        ):
            await execute_ai_turn(mock_db, self.tenant_id, self.conversation_id)

        created_message = next(
            item
            for item in mock_db.add.call_args_list[0].args
            if isinstance(item, Message)
        )
        create_delivery_mock.assert_called_once_with(
            tenant_id=self.tenant_id,
            message_id=created_message.id,
            now=ANY,
        )
        mock_db.add.assert_any_call(delivery)
        dispatch_delivery_mock.assert_called_once_with(delivery.id, self.tenant_id)
        self.assertEqual(
            [call.kwargs["event"] for call in realtime_broadcast_mock.await_args_list],
            ["message.created", "conversation.updated"],
        )
        self.assertTrue(
            all(
                call.kwargs["data"]["channel_id"] == str(channel.id)
                for call in realtime_broadcast_mock.await_args_list
            )
        )

    async def test_summarize_conversation_history(self) -> None:
        """Validates that summarize_conversation_history correctly gathers chat history and calls LLM."""
        from app.ai.service import summarize_conversation_history

        conv = Conversation(
            id=self.conversation_id,
            tenant_id=self.tenant_id,
            channel_id=self.channel_id,
            contact_id=self.contact_id,
            status=ConversationStatus.OPEN,
        )
        ai_config = ChannelAiConfig(
            id=uuid4(),
            tenant_id=self.tenant_id,
            channel_id=self.channel_id,
            provider="openai",
            model_name="gpt-4o-mini",
            api_key_encrypted=encrypt_secret("sk-test-123"),
        )
        msg1 = Message(
            id=uuid4(),
            tenant_id=self.tenant_id,
            conversation_id=self.conversation_id,
            direction=MessageDirection.INCOMING,
            message_type=MessageType.TEXT,
            body="Olá, gostaria de saber o valor do plano Pro.",
            created_at=None,
        )
        msg2 = Message(
            id=uuid4(),
            tenant_id=self.tenant_id,
            conversation_id=self.conversation_id,
            direction=MessageDirection.OUTGOING,
            message_type=MessageType.TEXT,
            body="O plano Pro custa R$ 199/mês.",
            sender_name="Carlos",
            created_at=None,
        )

        mock_db = MagicMock()
        mock_db.scalar.side_effect = [conv, ai_config]
        mock_db.scalars.return_value = [msg1, msg2]

        with patch("app.ai.service.call_llm") as mock_llm:
            mock_llm.return_value = ("🎯 **Motivo**: Preço do plano Pro\n📋 **Pontos**: Valor informado R$ 199\n⏳ **Status**: Aguardando cliente", False, None)
            summary = await summarize_conversation_history(mock_db, self.tenant_id, self.conversation_id)

            self.assertIn("Motivo", summary)
            self.assertIn("Preço do plano Pro", summary)
            mock_llm.assert_called_once()

    def test_get_channel_ai_config_router_role_check(self) -> None:
        """Validates that get_channel_ai_config correctly reads membership.role and returns config."""
        from app.ai.router import get_channel_ai_config
        from app.auth.dependencies import AuthContext
        from app.channels.models import WhatsAppChannel
        from app.users.models import TenantUser, User

        user = User(
            id=self.user_id,
            email="admin@example.com",
            name="Admin User",
            password_hash="hash",
            is_active=True,
            is_platform_admin=False,
        )
        membership = TenantUser(
            id=uuid4(),
            tenant_id=self.tenant_id,
            user_id=self.user_id,
            role="admin",
            is_active=True,
        )
        context = AuthContext(user=user, membership=membership)

        channel = WhatsAppChannel(
            id=self.channel_id,
            tenant_id=self.tenant_id,
            name="Principal",
            phone_number="5511999999999",
            provider=ChannelProvider.EVOLUTION_GO,
            status=ChannelStatus.CONNECTED,
        )
        ai_config = ChannelAiConfig(
            id=uuid4(),
            tenant_id=self.tenant_id,
            channel_id=self.channel_id,
            is_enabled=False,
            provider="openai",
            model_name="gpt-4o-mini",
            bot_name="IA Assistente",
            system_prompt="Prompt teste",
            handoff_prompt="Handoff teste",
            temperature=0.3,
            max_tokens=500,
        )

        mock_db = MagicMock()
        mock_db.scalar.side_effect = [channel, ai_config]

        result = get_channel_ai_config(
            channel_id=self.channel_id,
            db=mock_db,
            context=context,
        )

        self.assertEqual(result.channel_id, self.channel_id)
        self.assertEqual(result.provider, "openai")
        self.assertEqual(result.bot_name, "IA Assistente")
