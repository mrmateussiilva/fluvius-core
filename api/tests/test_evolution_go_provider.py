import asyncio
import json
import unittest
from datetime import UTC, datetime, timedelta
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
from app.providers.base import IgnoredWebhookEvent, IncomingMessageEditResult, SharedContact
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
                "ChatName": "Grupo Operacional" if is_group else "",
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
        self.assertEqual(
            self.provider.webhook_event_id(message_payload()),
            "message:MESSAGE-123",
        )

    def test_message_event_id_uses_message_identity_instead_of_envelope_id(self) -> None:
        payload = message_payload()
        payload["id"] = "ENVELOPE-456"

        self.assertEqual(
            self.provider.webhook_event_id(payload),
            "message:MESSAGE-123",
        )

    def test_parses_evolution_go_072_message_payload(self) -> None:
        result = asyncio.run(self.provider.handle_webhook(message_payload()))
        self.assertEqual(result.provider_message_id, "MESSAGE-123")
        self.assertEqual(result.from_number, "5527999999999")
        self.assertEqual(result.sender_name, "Cliente Teste")
        self.assertEqual(result.message_type, MessageType.TEXT)
        self.assertEqual(result.body, "Olá pelo WhatsApp")

    def test_parses_single_shared_contact(self) -> None:
        payload = message_payload()
        payload["data"]["Info"]["Type"] = "ContactMessage"
        payload["data"]["Message"] = {
            "contactMessage": {
                "displayName": "Maria Cliente",
                "vcard": (
                    "BEGIN:VCARD\nVERSION:3.0\nFN:Maria Cliente\n"
                    "ORG:Empresa Exemplo\nTEL;TYPE=CELL:+55 27 99999-9999\nEND:VCARD"
                ),
            }
        }

        result = asyncio.run(self.provider.handle_webhook(payload))

        self.assertEqual(result.message_type, MessageType.CONTACT)
        self.assertEqual(len(result.shared_contacts), 1)
        self.assertEqual(result.shared_contacts[0].display_name, "Maria Cliente")
        self.assertEqual(result.shared_contacts[0].phone_number, "5527999999999")
        self.assertEqual(result.shared_contacts[0].organization, "Empresa Exemplo")

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

    def test_parses_encrypted_edit_without_creating_an_empty_message(self) -> None:
        result = asyncio.run(
            self.provider.handle_webhook(load_fixture("message-edited-encrypted.json"))
        )

        self.assertIsInstance(result, IncomingMessageEditResult)
        self.assertEqual(result.provider_event_id, "EDIT-EVENT-1")
        self.assertEqual(
            result.target_provider_message_id,
            "ORIGINAL-MESSAGE-1",
        )
        self.assertIsNone(result.body)

    def test_parses_plaintext_protocol_edit(self) -> None:
        payload = message_payload()
        payload["data"]["Info"]["ID"] = "EDIT-EVENT-2"
        payload["data"]["Info"]["Edit"] = "1"
        payload["data"]["Message"] = {
            "protocolMessage": {
                "key": {"ID": "ORIGINAL-MESSAGE-2"},
                "editedMessage": {"extendedTextMessage": {"text": "Texto corrigido"}},
            }
        }

        result = asyncio.run(self.provider.handle_webhook(payload))

        self.assertIsInstance(result, IncomingMessageEditResult)
        self.assertEqual(
            result.target_provider_message_id,
            "ORIGINAL-MESSAGE-2",
        )
        self.assertEqual(result.body, "Texto corrigido")

    def test_ignores_reaction_removal(self) -> None:
        with self.assertRaisesRegex(
            IgnoredWebhookEvent,
            "Reações não geram mensagens",
        ):
            asyncio.run(self.provider.handle_webhook(load_fixture("reaction-removed.json")))

    def test_sanitizes_encrypted_edit_material(self) -> None:
        payload = message_payload()
        payload["data"]["Message"] = {
            "messageContextInfo": {"deviceListMetadata": {"senderKeyHash": "sensitive"}},
            "secretEncryptedMessage": {
                "encIV": "sensitive-iv",
                "encPayload": "sensitive-payload",
                "targetMessageKey": {"ID": "ORIGINAL-MESSAGE-3"},
            },
        }

        sanitized = self.provider.sanitize_webhook_payload(payload)
        message = sanitized["data"]["Message"]

        self.assertNotIn(
            "deviceListMetadata",
            message["messageContextInfo"],
        )
        self.assertNotIn("encIV", message["secretEncryptedMessage"])
        self.assertNotIn("encPayload", message["secretEncryptedMessage"])
        self.assertTrue(message["secretEncryptedMessage"]["encryptedPayloadRemoved"])

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

    def test_parses_wrapped_incoming_document_file(self) -> None:
        result = asyncio.run(
            self.provider.handle_webhook(load_fixture("document-with-caption-message.json"))
        )

        self.assertEqual(result.message_type, MessageType.DOCUMENT)
        self.assertEqual(result.body, "Contrato assinado")
        self.assertEqual(
            result.media_base64,
            "JVBERi0xLjcKZG9jdW1lbnRvIHJlY2ViaWRv",
        )
        self.assertEqual(result.media_content_type, "application/pdf")
        self.assertEqual(result.media_file_name, "contrato.pdf")

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

    def test_sends_group_mentions_as_jids(self) -> None:
        response = httpx.Response(
            200,
            request=httpx.Request("POST", "http://evolution-go:8080/send/text"),
            json={"data": {"Info": {"ID": "MENTION-MESSAGE-ID"}}},
        )
        with patch.object(
            self.provider,
            "_request",
            new=AsyncMock(return_value=response),
        ) as request:
            result = asyncio.run(
                self.provider.send_text(
                    None,
                    "120363018686549942@g.us",
                    "Oi @Maria",
                    mentioned_phones=["+55 (27) 99999-9999"],
                    idempotency_key="MENTION-MESSAGE-ID",
                )
            )

        body = request.await_args.kwargs["json"]
        self.assertTrue(result.success)
        self.assertEqual(body["mentionedJid"], ["5527999999999@s.whatsapp.net"])

    def test_sends_group_lid_mentions_as_jids(self) -> None:
        response = httpx.Response(
            200,
            request=httpx.Request("POST", "http://evolution-go:8080/send/text"),
            json={"data": {"Info": {"ID": "MENTION-LID-MESSAGE-ID"}}},
        )
        with patch.object(
            self.provider,
            "_request",
            new=AsyncMock(return_value=response),
        ) as request:
            result = asyncio.run(
                self.provider.send_text(
                    None,
                    "120363018686549942@g.us",
                    "Oi @Participante",
                    mentioned_jids=["964169518424559641@lid"],
                    idempotency_key="MENTION-LID-MESSAGE-ID",
                )
            )

        body = request.await_args.kwargs["json"]
        self.assertTrue(result.success)
        self.assertEqual(body["mentionedJid"], ["964169518424559641@lid"])

    def test_retries_only_failures_that_are_safe_before_delivery(self) -> None:
        request = httpx.Request("POST", "http://evolution-go:8080/send/text")
        connect_failure = self.provider._send_error_result(
            httpx.ConnectError("connection refused", request=request)
        )
        uncertain_failure = self.provider._send_error_result(
            httpx.ReadTimeout("response timeout", request=request)
        )

        self.assertFalse(connect_failure.success)
        self.assertTrue(connect_failure.retryable)
        self.assertFalse(uncertain_failure.success)
        self.assertFalse(uncertain_failure.retryable)
        self.assertIn("incerta", uncertain_failure.error)

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

    def test_sends_media_without_caption_omits_optional_fields(self) -> None:
        response = httpx.Response(
            200,
            request=httpx.Request("POST", "http://evolution-go:8080/send/media"),
            json={"data": {"Info": {"ID": "PHOTO-123"}}},
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
                    f"{settings.public_api_url}/storage/foto.png",
                    None,
                )
            )
        self.assertTrue(result.success)
        body = request.await_args.kwargs["json"]
        self.assertNotIn("caption", body)
        self.assertEqual(body["filename"], "foto.png")

    def test_sends_gif_as_document(self) -> None:
        response = httpx.Response(
            200,
            request=httpx.Request("POST", "http://evolution-go:8080/send/media"),
            json={"data": {"Info": {"ID": "GIF-123"}}},
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
                    f"{settings.public_api_url}/storage/meme.gif",
                    None,
                )
            )
        self.assertTrue(result.success)
        self.assertEqual(request.await_args.kwargs["json"]["type"], "document")

    def test_sends_media_using_internal_base_when_public_domain_is_blocked(self) -> None:
        response = httpx.Response(
            200,
            request=httpx.Request("POST", "http://evolution-go:8080/send/media"),
            json={"data": {"Info": {"ID": "PHOTO-123"}}},
        )
        provider = EvolutionGoProvider(
            webhook_base_url="https://fluvius.example",
            media_base_url="http://api:8000",
        )
        with (
            patch.object(
                settings,
                "public_api_url",
                "https://fluvius.example",
            ),
            patch.object(
                provider,
                "_request",
                new=AsyncMock(return_value=response),
            ) as request,
        ):
            result = asyncio.run(
                provider.send_media(
                    None,
                    "5527999999999",
                    "https://fluvius.example/storage/foto.png",
                    "Legenda",
                )
            )
        self.assertTrue(result.success)
        self.assertEqual(
            request.await_args.kwargs["json"]["url"],
            "http://api:8000/storage/foto.png",
        )

    def test_media_send_uses_extended_timeout(self) -> None:
        response = httpx.Response(
            200,
            request=httpx.Request("POST", "http://evolution-go:8080/send/media"),
            json={"data": {"Info": {"ID": "PHOTO-123"}}},
        )
        with patch.object(
            self.provider,
            "_request",
            new=AsyncMock(return_value=response),
        ) as request:
            asyncio.run(
                self.provider.send_media(
                    None,
                    "5527999999999",
                    f"{settings.public_api_url}/storage/foto.png",
                )
            )
        self.assertEqual(request.await_args.kwargs["timeout"], self.provider.media_timeout)

    def test_http_error_detail_includes_gateway_reason(self) -> None:
        response = httpx.Response(
            500,
            request=httpx.Request("POST", "http://evolution-go:8080/send/media"),
            json={"error": "Invalid file format: 'text/html'"},
        )
        request = httpx.Request("POST", "http://evolution-go:8080/send/media")
        exc = httpx.HTTPStatusError("server error", request=request, response=response)
        result = self.provider._send_error_result(exc)
        self.assertFalse(result.success)
        self.assertIn("Invalid file format", result.error or "")

    def test_http_error_detail_is_bounded_and_sanitized(self) -> None:
        response = httpx.Response(
            502,
            request=httpx.Request("POST", "http://evolution-go:8080/send/media"),
            content=b"<html>\n\n  " + b"x" * 500 + b"</html>",
            headers={"Content-Type": "text/html"},
        )
        request = httpx.Request("POST", "http://evolution-go:8080/send/media")
        exc = httpx.HTTPStatusError("server error", request=request, response=response)
        message = self.provider._http_error_message(exc)
        self.assertIn("HTTP 502", message)
        self.assertLessEqual(len(message), 200)
        self.assertNotIn("\n", message)

    def test_sends_native_contact_with_stable_id(self) -> None:
        response = httpx.Response(
            200,
            request=httpx.Request("POST", "http://evolution-go:8080/send/contact"),
            json={"data": {"Info": {"ID": "CONTACT-123"}}},
        )
        with patch.object(
            self.provider,
            "_request",
            new=AsyncMock(return_value=response),
        ) as request:
            result = asyncio.run(
                self.provider.send_contact(
                    None,
                    "5527998888888",
                    SharedContact(
                        display_name="Maria Cliente",
                        phone_number="5527999999999",
                        organization="Empresa Exemplo",
                    ),
                    idempotency_key="LOCAL-CONTACT-ID",
                )
            )

        self.assertTrue(result.success)
        self.assertEqual(result.provider_message_id, "CONTACT-123")
        self.assertEqual(request.await_args.args[:2], ("POST", "/send/contact"))
        self.assertEqual(
            request.await_args.kwargs["json"],
            {
                "number": "5527998888888",
                "vcard": {
                    "fullName": "Maria Cliente",
                    "phone": "5527999999999",
                    "organization": "Empresa Exemplo",
                },
                "id": "LOCAL-CONTACT-ID",
            },
        )

    def test_ignores_api_send_confirmation_event(self) -> None:
        with self.assertRaises(IgnoredWebhookEvent):
            asyncio.run(
                self.provider.handle_webhook(message_payload(from_me=True, event="SendMessage"))
            )

    def test_ignores_button_click_technical_event(self) -> None:
        with self.assertRaises(IgnoredWebhookEvent):
            asyncio.run(self.provider.handle_webhook(message_payload(event="ButtonClick")))

    def test_parses_group_messages(self) -> None:
        result = asyncio.run(
            self.provider.handle_webhook(load_fixture("group-message-sender-alt.json"))
        )
        self.assertTrue(result.is_group)
        self.assertEqual(result.chat_id, "120363018686549942")
        self.assertEqual(result.chat_name, "Grupo Operacional")
        self.assertEqual(result.provider_address, "120363018686549942@g.us")
        self.assertEqual(result.from_number, "120363018686549942")
        self.assertEqual(result.participant_phone, "5527999999999")
        self.assertEqual(result.participant_name, "Cliente Teste")
        self.assertEqual(result.body, "Mensagem de participante com SenderAlt")

    def test_group_lid_participant_without_sender_alt_is_not_stored_as_phone(
        self,
    ) -> None:
        result = asyncio.run(
            self.provider.handle_webhook(load_fixture("group-message-lid-participant.json"))
        )

        self.assertTrue(result.is_group)
        self.assertEqual(result.chat_id, "120363018686549942")
        self.assertEqual(result.from_number, "120363018686549942")
        self.assertIsNone(result.participant_phone)
        self.assertEqual(result.participant_name, "Cliente LID")

    def test_direct_lid_without_sender_alt_is_rejected_instead_of_stored_as_phone(
        self,
    ) -> None:
        payload = message_payload()
        payload["data"]["Info"].pop("SenderAlt")

        with self.assertRaisesRegex(
            ValueError,
            "Webhook Evolution Go sem ID ou remetente",
        ):
            asyncio.run(self.provider.handle_webhook(payload))

    def test_parses_group_directory_with_explicit_count_and_admin_role(self) -> None:
        result = self.provider._parse_group_directory(
            {
                "data": {
                    "Groups": [
                        {
                            "JID": "120363018686549942@g.us",
                            "Subject": "Grupo Comercial",
                            "Description": "Atendimento B2B",
                            "ParticipantCount": "42",
                            "Participants": [
                                {
                                    "JID": "5527999999999@s.whatsapp.net",
                                    "PushName": "Coordenador",
                                    "Role": "admin",
                                },
                                {
                                    "JID": "172434498003125@lid",
                                    "PushName": "Participante LID",
                                    "Role": "member",
                                },
                            ],
                        }
                    ]
                }
            }
        )

        self.assertEqual(len(result), 1)
        group = result[0]
        self.assertEqual(group.group_id, "120363018686549942")
        self.assertEqual(group.provider_address, "120363018686549942@g.us")
        self.assertEqual(group.name, "Grupo Comercial")
        self.assertEqual(group.about, "Atendimento B2B")
        self.assertEqual(group.member_count, 42)
        self.assertEqual(len(group.members), 2)
        self.assertEqual(group.members[0].phone_number, "5527999999999")
        self.assertEqual(group.members[0].provider_jid, "5527999999999@s.whatsapp.net")
        self.assertEqual(group.members[0].name, "Coordenador")
        self.assertTrue(group.members[0].is_admin)
        self.assertEqual(group.members[1].phone_number, "172434498003125")
        self.assertEqual(group.members[1].provider_jid, "172434498003125@lid")
        self.assertEqual(group.members[1].name, "Participante LID")

    def test_parses_group_profile_with_member_count_without_member_list(self) -> None:
        result = self.provider._parse_group_profile(
            info={
                "data": {
                    "GroupInfo": {
                        "Name": "Grupo Diretoria",
                        "Topic": "Decisões operacionais",
                        "MemberCount": 12,
                    }
                }
            },
            avatar={"data": {"URL": "https://example.test/group.jpg"}},
        )

        self.assertEqual(result.push_name, "Grupo Diretoria")
        self.assertEqual(result.about, "Decisões operacionais")
        self.assertEqual(result.group_member_count, 12)
        self.assertEqual(result.group_members, [])
        self.assertEqual(result.profile_picture_url, "https://example.test/group.jpg")

    def test_group_members_preserve_lid_targets_without_real_phone(self) -> None:
        result = self.provider._parse_group_profile(
            info={
                "data": {
                    "GroupInfo": {
                        "Name": "Grupo Operacional",
                        "Participants": [
                            {
                                "ID": "964169518424559641",
                                "PushName": "ID Interno",
                                "Role": "admin",
                            },
                            {
                                "PhoneNumber": "5527999999999",
                                "PushName": "Telefone Real",
                            },
                            {
                                "JID": "172434498003125@lid",
                                "PushName": "Participante LID",
                            },
                        ],
                    }
                }
            },
            avatar=None,
        )

        self.assertEqual(len(result.group_members), 3)
        self.assertEqual(result.group_members[0].phone_number, "964169518424559641")
        self.assertEqual(result.group_members[0].provider_jid, "964169518424559641@lid")
        self.assertEqual(result.group_members[0].name, "ID Interno")
        self.assertTrue(result.group_members[0].is_admin)
        self.assertEqual(result.group_members[1].phone_number, "5527999999999")
        self.assertIsNone(result.group_members[1].provider_jid)
        self.assertEqual(result.group_members[1].name, "Telefone Real")
        self.assertEqual(result.group_members[2].phone_number, "172434498003125")
        self.assertEqual(result.group_members[2].provider_jid, "172434498003125@lid")

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
        self.assertEqual(
            result.error,
            "Evolution Go respondeu com HTTP 400: invalid request",
        )

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
                        "FullName": "Maria da Agenda",
                        "FirstName": "Maria",
                        "PushName": "Cliente Teste",
                        "BusinessName": "Empresa Teste",
                    }
                ]
            },
        )
        self.assertTrue(result.is_on_whatsapp)
        self.assertEqual(result.address_book_name, "Maria da Agenda")
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

    def test_ignores_status_broadcast_receipt(self) -> None:
        payload = receipt_payload()
        payload["data"]["Chat"] = "status@broadcast"
        with self.assertRaises(IgnoredWebhookEvent):
            self.provider.handle_message_status(payload)

    def test_receipt_event_id_is_stable_and_state_specific(self) -> None:
        delivered = self.provider.webhook_event_id(receipt_payload())
        read = self.provider.webhook_event_id(receipt_payload("Read"))
        self.assertTrue(delivered.startswith("receipt:"))
        self.assertNotEqual(delivered, read)

    def test_message_status_only_advances(self) -> None:
        self.assertTrue(can_advance_message_status(MessageStatus.SENT, MessageStatus.DELIVERED))
        self.assertTrue(can_advance_message_status(MessageStatus.SENT, MessageStatus.READ))
        self.assertFalse(can_advance_message_status(MessageStatus.READ, MessageStatus.DELIVERED))
        self.assertFalse(can_advance_message_status(MessageStatus.FAILED, MessageStatus.READ))

    def test_history_sync_skips_messages_older_than_max_age(self) -> None:
        old_epoch = int((datetime.now(UTC) - timedelta(days=60)).timestamp())
        recent_epoch = int((datetime.now(UTC) - timedelta(days=2)).timestamp())

        envelope = {"instanceId": "inst-1", "instanceName": "fluvius"}
        old_msg = {
            "key": {"id": "old-msg-1", "remoteJid": "5511999999999@s.whatsapp.net"},
            "message": {"conversation": "Mensagem muito antiga"},
            "messageTimestamp": old_epoch,
        }
        recent_msg = {
            "key": {"id": "recent-msg-1", "remoteJid": "5511999999999@s.whatsapp.net"},
            "message": {"conversation": "Mensagem recente"},
            "messageTimestamp": recent_epoch,
        }
        conversation = {"id": "5511999999999@s.whatsapp.net"}

        self.assertIsNone(
            EvolutionGoProvider._history_message_payload(envelope, old_msg, conversation)
        )
    def test_parses_ephemeral_and_view_once_messages(self) -> None:
        payload = message_payload()
        payload["data"]["Message"] = {
            "ephemeralMessage": {
                "message": {
                    "viewOnceMessage": {
                        "message": {
                            "imageMessage": {
                                "caption": "Foto temporária",
                                "url": "https://example.com/photo.jpg",
                                "mimetype": "image/jpeg",
                            }
                        }
                    }
                }
            }
        }
        loop = asyncio.new_event_loop()
        try:
            result = loop.run_until_complete(self.provider.handle_webhook(payload))
        finally:
            loop.close()
        self.assertEqual(result.body, "Foto temporária")
        self.assertEqual(result.message_type, MessageType.IMAGE)
        self.assertEqual(result.media_url, "https://example.com/photo.jpg")

    def test_parses_button_and_list_responses(self) -> None:
        button_payload = message_payload()
        button_payload["data"]["Message"] = {
            "buttonsResponseMessage": {
                "selectedDisplayText": "Opção 1: Suporte",
                "selectedButtonId": "btn_1",
            }
        }
        loop = asyncio.new_event_loop()
        try:
            result = loop.run_until_complete(self.provider.handle_webhook(button_payload))
        finally:
            loop.close()
        self.assertEqual(result.body, "Opção 1: Suporte")


if __name__ == "__main__":
    unittest.main()
