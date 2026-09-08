"""Typebot HTTP boundary. No database, WhatsApp credentials or gateway imports."""

import logging
import re
from dataclasses import dataclass
from urllib.parse import urlsplit

import httpx

logger = logging.getLogger(__name__)
PUBLIC_ID_PATTERN = r"^[A-Za-z0-9_-]{1,255}$"


class TypebotError(Exception):
    """Safe error code; never includes response bodies, URLs or request content."""


def rich_text_to_plain(nodes: list) -> str:
    def render(node: object, depth: int = 0) -> str:
        if not isinstance(node, dict) or depth > 50:
            raise TypebotError("invalid_rich_text")
        if "text" in node:
            if not isinstance(node["text"], str):
                raise TypebotError("invalid_rich_text")
            return node["text"]
        kind = node.get("type")
        if kind is not None and not isinstance(kind, str):
            raise TypebotError("invalid_rich_text")
        if kind in {"br", "break"}:
            return "\n"
        children = node.get("children", [])
        if not isinstance(children, list):
            raise TypebotError("invalid_rich_text")
        value = "".join(render(child, depth + 1) for child in children)
        if kind in {"p", "div", "li", "ul", "ol", "blockquote", "h1", "h2", "h3"}:
            return value + ("" if value.endswith("\n") else "\n")
        return value

    return "".join(render(node) for node in nodes).strip()


@dataclass(frozen=True)
class TypebotReply:
    session_id: str | None
    result_id: str | None
    texts: list[str]
    finished: bool


def parse_reply(data: object, *, starting: bool) -> TypebotReply:
    if not isinstance(data, dict) or not isinstance(data.get("messages"), list):
        raise TypebotError("invalid_response")
    session_id = data.get("sessionId")
    result_id = data.get("resultId")
    for value in (session_id, result_id):
        if value is not None and (
            not isinstance(value, str) or not re.fullmatch(PUBLIC_ID_PATTERN, value)
        ):
            raise TypebotError("invalid_identifier")
    if starting and not session_id:
        raise TypebotError("missing_session_id")
    if data.get("input") is not None and not isinstance(data["input"], dict):
        raise TypebotError("invalid_input")
    actions = data.get("clientSideActions", [])
    if not isinstance(actions, list):
        raise TypebotError("invalid_actions")
    if actions:
        logger.info("Typebot client-side actions ignored; count=%d", len(actions))
    texts = []
    for bubble in data["messages"]:
        if not isinstance(bubble, dict):
            raise TypebotError("invalid_message")
        if bubble.get("type") != "text":
            logger.info("Typebot non-text bubble ignored")
            continue
        content = bubble.get("content")
        if (
            not isinstance(content, dict)
            or content.get("type") != "richText"
            or not isinstance(content.get("richText"), list)
        ):
            raise TypebotError("invalid_text_content")
        value = rich_text_to_plain(content["richText"])
        if value:
            texts.append(value)
    return TypebotReply(session_id, result_id, texts, not data.get("input"))


class TypebotClient:
    def __init__(self, base_url: str):
        try:
            parsed = urlsplit(base_url)
            parsed.port  # Validate malformed/non-numeric ports before any request.
            httpx.URL(base_url)
        except (ValueError, httpx.InvalidURL):
            raise TypebotError("invalid_base_url") from None
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or any(char.isspace() for char in base_url)
        ):
            raise TypebotError("invalid_base_url")
        self.base_url = base_url.rstrip("/")

    async def _post(self, path: str, payload: dict, *, starting: bool) -> TypebotReply:
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(30, connect=5), follow_redirects=False
            ) as client:
                response = await client.post(f"{self.base_url}/api/v1/{path}", json=payload)
            if not 200 <= response.status_code < 300:
                raise TypebotError("http_error")
            return parse_reply(response.json(), starting=starting)
        except httpx.RequestError:
            raise TypebotError("transport_error") from None
        except (ValueError, RecursionError):
            raise TypebotError("invalid_json") from None

    async def start(self, public_id: str, message: str, variables: dict[str, str]) -> TypebotReply:
        # Direct consumption of message requires an input-first flow. Bubble-first
        # flows must explicitly use fluvius_initial_message; never replay via continue.
        if not re.fullmatch(PUBLIC_ID_PATTERN, public_id):
            raise TypebotError("invalid_public_id")
        return await self._post(
            f"typebots/{public_id}/startChat",
            {
                "message": {"type": "text", "text": message},
                "prefilledVariables": variables,
                "textBubbleContentFormat": "richText",
                "isStreamEnabled": False,
            },
            starting=True,
        )

    async def continue_chat(self, session_id: str, message: str) -> TypebotReply:
        if not re.fullmatch(PUBLIC_ID_PATTERN, session_id):
            raise TypebotError("invalid_session_id")
        reply = await self._post(
            f"sessions/{session_id}/continueChat", {"message": message}, starting=False
        )
        if reply.session_id is not None and reply.session_id != session_id:
            raise TypebotError("session_mismatch")
        return reply
