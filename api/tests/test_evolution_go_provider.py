import asyncio
import json
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import UUID

import httpx

from app.common.enums import (
    ChannelProvider,
    ChannelStatus,
    MessageDirection,
    MessageStatus,
    MessageType,
)
from app.config import settings
from app.providers.base import IgnoredWebhookEvent
from app.providers.evolution_go import EvolutionGoProvider
from app.providers.status_updates import can_advance_message_status

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "evolution_go" / "0.7.2"


def load_fixture(name: str) -> dict:
    with (FIXTURE_DIR / name).open(encoding="utf-8") as fixture:
        return json.load(fixture)


def message_payload(
    *,
    from_me: bool = False,
    event: str = "Message",
    is_group: bool = False,
) -> dict:
    return {
        "event": event,
        "instanceId": "instance-id",
        "instanceName": "pessoal",
        "instanceToken": "instance-secret",
        "data": {
            "Info": {
                "ID": "MESSAGE-123",
                "Sender": "172434498003125@lid",
                "SenderAlt": "5527999999999@s.whatsapp.net",
                "RecipientAlt": "5527998888888@s.whatsapp.net",
                "Chat": "120363018686549942@g.us" if is_group else "172434498003125@lid",
                "IsFromMe": from_me,
                "IsGroup": is_group,
                "PushName": "Cliente Teste",
                "Timestamp": "2026-07-21T20:48:18-03:00",
                "Type": "text",
            },
            "Message": {"conversation": "Olá pelo WhatsApp"},
        },
    }


def receipt_payload(state: str = "Delivered") -> dict:
    return {
        "event": "Receipt",
        "state": state,
        "instanceId": "instance-id",
        "instanceName": "pessoal",
        "instanceToken": "instance-secret",
        "data": {
            "Chat": "5527999999999@s.whatsapp.net",
            "MessageIDs": ["OUTGOING-456"],
            "Timestamp": "2026-07-21T21:10:00-03:00",
            "Type": state.lower(),
        },
    }


class EvolutionGoWebhookTest(unittest.TestCase):
    def setUp(self) -> None:
        self.provider = EvolutionGoProvider(
            base_url="http://evolution-go:8080",
            api_key="instance-secret",
        )

    def test_accepts_instance_token_when_shared_header_is_absent(self) -> None:
        self.assertTrue(
            self.provider.verify_webhook(
                message_payload(),
                provided_secret=None,
                expected_secret="shared-secret",
            )
        )

    def test_rejects_an_invalid_instance_token(self) -> None:
        payload = message_payload()
        payload["instanceToken"] = "wrong-token"
        self.assertFalse(
            self.provider.verify_webhook(
                payload,
                provided_secret=None,
                expected_secret="shared-secret",
            )
        )

    def test_sanitizes_instance_token_before_persistence(self) -> None:
        payload = message_payload()
        payload["data"]["Message"]["base64"] = "YmluYXJ5"
        sanitized = self.provider.sanitize_webhook_payload(payload)
        self.assertNotIn("instanceToken", sanitized)
        self.assertNotIn("base64", sanitized["data"]["Message"])
        self.assertEqual(payload["data"]["Message"]["base64"], "YmluYXJ5")
        self.assertEqual(self.provider.webhook_event_id(message_payload()), "MESSAGE-123")

    def test_parses_evolution_go_072_message_payload(self) -> None:
        result = asyncio.run(self.provider.handle_webhook(message_payload()))
        self.assertEqual(result.provider_message_id, "MESSAGE-123")
        self.assertEqual(result.from_number, "5527999999999")
        self.assertEqual(result.sender_name, "Cliente Teste")
        self.assertEqual(result.message_type, MessageType.TEXT)
        self.assertEqual(result.body, "Olá pelo WhatsApp")

    def test_parses_messages_sent_from_the_connected_phone(self) -> None:
        result = asyncio.run(self.provider.handle_webhook(message_payload(from_me=True)))
        self.assertEqual(result.direction, MessageDirection.OUTGOING)
        self.assertEqual(result.from_number, "5527998888888")
        self.assertIsNone(result.sender_name)

    def test_parses_quoted_message_context(self) -> None:
        payload = message_payload()
        payload["data"]["Message"] = {
            "extendedTextMessage": {
                "text": "Resposta citada",
                "contextInfo": {"stanzaID": "ORIGINAL-123"},
            }
        }
        result = asyncio.run(self.provider.handle_webhook(payload))
        self.assertEqual(result.reply_to_provider_message_id, "ORIGINAL-123")

    def test_parses_incoming_image_file(self) -> None:
        payload = message_payload()
        payload["data"]["Info"]["Type"] = "media"
        payload["data"]["Message"] = {
            "base64": "aW1hZ2Vt",
            "imageMessage": {
                "mimetype": "image/jpeg",
                "caption": "Foto recebida",
                "fileLength": "6",
            },
        }

        result = asyncio.run(self.provider.handle_webhook(payload))

        self.assertEqual(result.message_type, MessageType.IMAGE)
        self.assertEqual(result.body, "Foto recebida")
        self.assertEqual(result.media_base64, "aW1hZ2Vt")
        self.assertEqual(result.media_content_type, "image/jpeg")

    def test_parses_video_audio_and_sticker_types(self) -> None:
        cases = (
            ("videoMessage", "video/mp4", MessageType.VIDEO),
            ("audioMessage", "audio/ogg; codecs=opus", MessageType.AUDIO),
            ("stickerMessage", "image/webp", MessageType.STICKER),
        )
        for key, content_type, expected in cases:
            with self.subTest(key=key):
                payload = message_payload()
                payload["data"]["Message"] = {
                    "base64": "bWVkaWE=",
                    key: {"mimetype": content_type},
                }
                result = asyncio.run(self.provider.handle_webhook(payload))
                self.assertEqual(result.message_type, expected)
                self.assertEqual(result.media_content_type, content_type)

    def test_sends_reply_with_stable_id_and_participant_jid(self) -> None:
        response = httpx.Response(
            200,
            request=httpx.Request("POST", "http://evolution-go:8080/send/text"),
            json={"data": {"Info": {"ID": "LOCAL-MESSAGE-ID"}}},
        )
        with patch.object(
            self.provider,
            "_request",
            new=AsyncMock(return_value=response),
        ) as request:
            result = asyncio.run(
                self.provider.send_text(
                    None,
                    "5527999999999",
                    "Resposta",
                    reply_to_provider_message_id="ORIGINAL-123",
                    reply_to_participant="5527999999999",
                    idempotency_key="LOCAL-MESSAGE-ID",
                )
            )
        body = request.await_args.kwargs["json"]
        self.assertTrue(result.success)
        self.assertEqual(body["id"], "LOCAL-MESSAGE-ID")
        self.assertEqual(body["quoted"]["messageId"], "ORIGINAL-123")
        self.assertEqual(body["quoted"]["participant"], "5527999999999@s.whatsapp.net")

    def test_sends_video_using_internal_storage_url(self) -> None:
        response = httpx.Response(
            200,
            request=httpx.Request("POST", "http://evolution-go:8080/send/media"),
            json={"data": {"Info": {"ID": "VIDEO-123"}}},
        )
        with patch.object(
            self.provider,
            "_request",
            new=AsyncMock(return_value=response),
        ) as request:
            result = asyncio.run(
                self.provider.send_media(
                    None,
                    "5527999999999",
                    f"{settings.public_api_url}/storage/video.mp4",
                    "Legenda",
                )
            )
        self.assertTrue(result.success)
        self.assertEqual(request.await_args.args[:2], ("POST", "/send/media"))
        self.assertEqual(request.await_args.kwargs["json"]["type"], "video")
        self.assertEqual(
            request.await_args.kwargs["json"]["url"],
            "http://api:8000/storage/video.mp4",
        )

    def test_sends_webp_as_sticker(self) -> None:
        response = httpx.Response(
            200,
            request=httpx.Request("POST", "http://evolution-go:8080/send/sticker"),
            json={"data": {"Info": {"ID": "STICKER-123"}}},
        )
        with patch.object(
            self.provider,
            "_request",
            new=AsyncMock(return_value=response),
        ) as request:
            result = asyncio.run(
                self.provider.send_media(
                    None,
                    "5527999999999",
                    f"{settings.public_api_url}/storage/figurinha.webp",
                )
            )
        self.assertTrue(result.success)
        self.assertEqual(request.await_args.args[:2], ("POST", "/send/sticker"))
        self.assertEqual(
            request.await_args.kwargs["json"]["sticker"],
            "http://api:8000/storage/figurinha.webp",
        )

    def test_ignores_api_send_confirmation_event(self) -> None:
        with self.assertRaises(IgnoredWebhookEvent):
            asyncio.run(
                self.provider.handle_webhook(
                    message_payload(from_me=True, event="SendMessage")
                )
            )

    def test_ignores_button_click_technical_event(self) -> None:
        with self.assertRaises(IgnoredWebhookEvent):
            asyncio.run(
                self.provider.handle_webhook(
                    message_payload(event="ButtonClick")
                )
            )

    def test_ignores_group_messages(self) -> None:
        with self.assertRaises(IgnoredWebhookEvent):
            asyncio.run(self.provider.handle_webhook(message_payload(is_group=True)))

    def test_parses_connected_status_envelope(self) -> None:
        result = self.provider._parse_status(load_fixture("status-connected.json"))
        self.assertEqual(result.status, ChannelStatus.CONNECTED)
        self.assertEqual(result.raw_status, "connected=true,loggedIn=true")

    def test_status_poll_does_not_reconfigure_the_webhook(self) -> None:
        response = httpx.Response(
            200,
            request=httpx.Request("GET", "http://evolution-go:8080/instance/status"),
            json=load_fixture("status-connected.json"),
        )
        with patch.object(
            self.provider,
            "_request",
            new=AsyncMock(return_value=response),
        ) as request:
            result = asyncio.run(self.provider.get_status(None))

        self.assertEqual(result.status, ChannelStatus.CONNECTED)
        request.assert_awaited_once_with("GET", "/instance/status")

    def test_qr_reports_connected_when_session_is_already_logged_in(self) -> None:
        connect_response = httpx.Response(
            200,
            request=httpx.Request("POST", "http://evolution-go:8080/instance/connect"),
            json={"message": "success", "data": {}},
        )
        qr_response = httpx.Response(
            400,
            request=httpx.Request("GET", "http://evolution-go:8080/instance/qr"),
            json=load_fixture("qr-session-already-logged-in.json"),
        )
        channel = SimpleNamespace(
            id=UUID("5a113028-0944-4051-86e2-7c139b02820a"),
            provider=ChannelProvider.EVOLUTION_GO,
        )
        with patch.object(
            self.provider,
            "_request",
            new=AsyncMock(side_effect=[connect_response, qr_response]),
        ):
            result = asyncio.run(self.provider.get_qr_code(channel))
        self.assertEqual(result.status, ChannelStatus.CONNECTED)
        self.assertIsNone(result.qr_code)
        self.assertIsNone(result.pairing_code)
        self.assertIsNone(result.error)

    def test_qr_keeps_unrecognized_bad_request_as_failure(self) -> None:
        connect_response = httpx.Response(
            200,
            request=httpx.Request("POST", "http://evolution-go:8080/instance/connect"),
            json={"message": "success", "data": {}},
        )
        qr_response = httpx.Response(
            400,
            request=httpx.Request("GET", "http://evolution-go:8080/instance/qr"),
            json={"error": "invalid request"},
        )
        channel = SimpleNamespace(
            id=UUID("5a113028-0944-4051-86e2-7c139b02820a"),
            provider=ChannelProvider.EVOLUTION_GO,
        )
        with patch.object(
            self.provider,
            "_request",
            new=AsyncMock(side_effect=[connect_response, qr_response]),
        ):
            result = asyncio.run(self.provider.get_qr_code(channel))
        self.assertEqual(result.status, ChannelStatus.FAILED)
        self.assertEqual(result.error, "Evolution Go respondeu com HTTP 400")

    def test_configures_webhook_for_channel(self) -> None:
        response = httpx.Response(
            200,
            request=httpx.Request("POST", "http://evolution-go:8080/instance/connect"),
            json={"message": "success", "data": {}},
        )
        provider = EvolutionGoProvider(
            base_url="http://evolution-go:8080",
            api_key="instance-secret",
            webhook_base_url="http://api:8000",
        )
        channel = SimpleNamespace(
            id=UUID("5a113028-0944-4051-86e2-7c139b02820a"),
            provider=ChannelProvider.EVOLUTION_GO,
        )
        with patch.object(
            provider,
            "_request",
            new=AsyncMock(return_value=response),
        ) as request:
            asyncio.run(provider._configure_webhook(channel))
        self.assertEqual(request.await_args.args[:2], ("POST", "/instance/connect"))
        payload = request.await_args.kwargs["json"]
        self.assertEqual(
            payload["webhookUrl"],
            "http://api:8000/api/v1/webhooks/whatsapp/evolution_go/"
            "5a113028-0944-4051-86e2-7c139b02820a",
        )
        self.assertEqual(payload["subscribe"], provider.webhook_events)

    def test_extracts_message_id_from_send_response(self) -> None:
        response = {
            "message": "success",
            "data": {
                "Info": {"ID": "OUTGOING-456", "IsFromMe": True},
                "Message": {"extendedTextMessage": {"text": "Resposta"}},
            },
        }
        self.assertEqual(self.provider._message_id(response), "OUTGOING-456")

    def test_parses_contact_profile_from_evolution_sources(self) -> None:
        result = self.provider._parse_contact_profile(
            phone_number="5527999999999",
            check={
                "data": {
                    "Users": [
                        {
                            "IsInWhatsapp": True,
                            "VerifiedName": "Empresa Verificada",
                        }
                    ]
                }
            },
            info={
                "data": {
                    "Users": {
                        "5527999999999@s.whatsapp.net": {
                            "Status": "Atendimento em horário comercial"
                        }
                    }
                }
            },
            avatar={"data": {"URL": "https://example.test/avatar.jpg"}},
            contacts={
                "data": [
                    {
                        "Jid": "5527999999999@s.whatsapp.net",
                        "PushName": "Cliente Teste",
                        "BusinessName": "Empresa Teste",
                    }
                ]
            },
        )
        self.assertTrue(result.is_on_whatsapp)
        self.assertEqual(result.push_name, "Cliente Teste")
        self.assertEqual(result.business_name, "Empresa Teste")
        self.assertEqual(result.verified_name, "Empresa Verificada")
        self.assertEqual(result.about, "Atendimento em horário comercial")
        self.assertEqual(result.profile_picture_url, "https://example.test/avatar.jpg")

    def test_contact_profile_rejects_non_http_avatar(self) -> None:
        result = self.provider._parse_contact_profile(
            phone_number="5527999999999",
            check=None,
            info=None,
            avatar={"data": {"URL": "javascript:alert(1)"}},
            contacts=None,
        )
        self.assertIsNone(result.profile_picture_url)

    def test_parses_delivered_receipt(self) -> None:
        result = self.provider.handle_message_status(receipt_payload())
        self.assertIsNotNone(result)
        self.assertEqual(result.provider_message_ids, ["OUTGOING-456"])
        self.assertEqual(result.status, MessageStatus.DELIVERED)
        self.assertIsNotNone(result.timestamp)

    def test_parses_read_receipt(self) -> None:
        result = self.provider.handle_message_status(receipt_payload("Read"))
        self.assertIsNotNone(result)
        self.assertEqual(result.status, MessageStatus.READ)

    def test_ignores_read_self_receipt(self) -> None:
        with self.assertRaises(IgnoredWebhookEvent):
            self.provider.handle_message_status(receipt_payload("ReadSelf"))

    def test_receipt_event_id_is_stable_and_state_specific(self) -> None:
        delivered = self.provider.webhook_event_id(receipt_payload())
        read = self.provider.webhook_event_id(receipt_payload("Read"))
        self.assertTrue(delivered.startswith("receipt:"))
        self.assertNotEqual(delivered, read)

    def test_message_status_only_advances(self) -> None:
        self.assertTrue(
            can_advance_message_status(MessageStatus.SENT, MessageStatus.DELIVERED)
        )
        self.assertTrue(can_advance_message_status(MessageStatus.SENT, MessageStatus.READ))
        self.assertFalse(
            can_advance_message_status(MessageStatus.READ, MessageStatus.DELIVERED)
        )
        self.assertFalse(
            can_advance_message_status(MessageStatus.FAILED, MessageStatus.READ)
        )


if __name__ == "__main__":
    unittest.main()
