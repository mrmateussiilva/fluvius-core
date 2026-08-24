import unittest
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import httpx

from app.ai.models import ChannelAiConfig
from app.ai.schemas import AiConfigUpdate
from app.ai.service import (
    call_llm,
    execute_ai_turn,
    get_or_create_ai_config,
    update_ai_config,
)
from app.common.enums import (
    ChannelProvider,
    ChannelStatus,
    ContactKind,
    ConversationStatus,
    MessageDirection,
    MessageStatus,
    MessageType,
)
from app.contacts.models import Contact
from app.conversations.models import Conversation
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
