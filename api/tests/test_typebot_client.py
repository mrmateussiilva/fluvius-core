import unittest
from unittest.mock import patch

import httpx

from app.bots.typebot.client import TypebotClient, TypebotError, parse_reply, rich_text_to_plain


def bubble(value):
    return {
        "type": "text",
        "content": {
            "type": "richText",
            "richText": [
                {"type": "p", "children": [{"text": value}]},
            ],
        },
    }


class TypebotClientTest(unittest.IsolatedAsyncioTestCase):
    def test_malformed_rich_text_is_a_safe_domain_error(self):
        for nodes in [[{"type": []}], [{"children": {}}], [{"text": 42}], [None]]:
            with self.subTest(nodes=nodes), self.assertRaises(TypebotError):
                rich_text_to_plain(nodes)

    def test_nested_rich_text_preserves_paragraphs_and_breaks(self):
        self.assertEqual(
            rich_text_to_plain(
                [
                    {
                        "type": "p",
                        "children": [
                            {"text": "Olá "},
                            {"type": "a", "children": [{"text": "Mateus"}]},
                            {"type": "br"},
                            {"text": "Tudo bem?"},
                        ],
                    },
                    {"type": "p", "children": [{"text": ""}]},
                    {"type": "p", "children": [{"text": "Outro parágrafo"}]},
                ]
            ),
            "Olá Mateus\nTudo bem?\n\nOutro parágrafo",
        )

    async def test_start_preserves_message_and_context_and_continue_uses_session(self):
        client = TypebotClient("https://typebot.example")
        with patch(
            "httpx.AsyncClient.post",
            return_value=httpx.Response(
                200,
                json={
                    "sessionId": "session-1",
                    "messages": [bubble("Olá")],
                    "input": {"type": "text input"},
                },
            ),
        ) as post:
            reply = await client.start(
                "published-bot", "Preciso consultar meu pedido", {"contact_name": "Mateus"}
            )
            self.assertEqual(reply.session_id, "session-1")
            self.assertEqual(
                post.call_args.kwargs["json"]["message"],
                {"type": "text", "text": "Preciso consultar meu pedido"},
            )
            self.assertEqual(
                post.call_args.kwargs["json"]["prefilledVariables"], {"contact_name": "Mateus"}
            )
            self.assertNotIn("isOnlyRegistering", post.call_args.kwargs["json"])
            post.assert_awaited_once()
            await client.continue_chat(reply.session_id, "Mateus")
            self.assertEqual(
                post.call_args.args[0],
                "https://typebot.example/api/v1/sessions/session-1/continueChat",
            )
            self.assertEqual(post.call_args.kwargs["json"], {"message": "Mateus"})

    async def test_http_errors_invalid_json_and_missing_session_are_not_success(self):
        for response in [
            httpx.Response(500, text="secret error"),
            httpx.Response(200, text="not json"),
            httpx.Response(302, headers={"location": "http://other.example"}),
            httpx.Response(200, json={"messages": []}),
            httpx.Response(200, json={"sessionId": "s", "messages": {}}),
        ]:
            with (
                self.subTest(response=response),
                patch("httpx.AsyncClient.post", return_value=response) as post,
            ):
                with self.assertRaises(TypebotError) as caught:
                    await TypebotClient("https://typebot.example").start("bot", "hello", {})
                self.assertNotIn("secret", str(caught.exception))
                self.assertEqual(post.call_count, 1)

    async def test_timeout_and_refused_connection_are_not_retried(self):
        for error in [httpx.ReadTimeout("secret"), httpx.ConnectError("secret")]:
            with (
                self.subTest(error=error),
                patch("httpx.AsyncClient.post", side_effect=error) as post,
            ):
                with self.assertRaisesRegex(TypebotError, "transport_error"):
                    await TypebotClient("https://typebot.example").start("bot", "hello", {})
                self.assertEqual(post.call_count, 1)

    def test_unsupported_bubbles_and_client_actions_are_ignored_safely(self):
        with self.assertLogs("app.bots.typebot.client", level="INFO") as logs:
            reply = parse_reply(
                {
                    "sessionId": "s",
                    "messages": [{"type": "image", "content": "secret"}, bubble("Texto")],
                    "clientSideActions": [{"scriptToExecute": {"content": "secret"}}],
                },
                starting=True,
            )
        self.assertEqual(reply.texts, ["Texto"])
        self.assertNotIn("secret", " ".join(logs.output))

    async def test_path_injection_and_invalid_base_url_rejected(self):
        for url in [
            "",
            "file:///etc/passwd",
            "https://user:password@example.com",
            "https://example.com?target=elsewhere",
            "http://[invalid",
            "https://example.com:invalid",
        ]:
            with self.subTest(url=url), self.assertRaises(TypebotError):
                TypebotClient(url)
        with patch("httpx.AsyncClient.post") as post:
            with self.assertRaises(TypebotError):
                await TypebotClient("https://typebot.example").start("../other", "hello", {})
            post.assert_not_called()

    async def test_continue_rejects_a_different_session_identifier(self):
        with patch(
            "httpx.AsyncClient.post",
            return_value=httpx.Response(
                200,
                json={
                    "sessionId": "different-session",
                    "messages": [],
                },
            ),
        ):
            with self.assertRaisesRegex(TypebotError, "session_mismatch"):
                await TypebotClient("https://typebot.example").continue_chat(
                    "expected-session", "Hello"
                )
