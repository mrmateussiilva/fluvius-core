import asyncio
import copy
import mimetypes
from datetime import UTC, datetime
from hashlib import sha256
from secrets import compare_digest
from typing import Any

import httpx

from app.channels.models import WhatsAppChannel
from app.common.enums import (
    ChannelProvider,
    ChannelStatus,
    MessageDirection,
    MessageStatus,
    MessageType,
)
from app.config import settings
from app.providers.base import (
    ChannelStatusResult,
    ContactProfileResult,
    GroupDirectoryEntry,
    GroupMemberProfile,
    IgnoredWebhookEvent,
    IncomingMessageEditResult,
    IncomingMessageResult,
    MessageStatusUpdateResult,
    QRCodeResult,
    SendResult,
    WhatsAppProvider,
)
from app.providers.evolution_circuit import evolution_circuit


class EvolutionGoProvider(WhatsAppProvider):
    """Initial Evolution Go adapter.

    Route and payload constants are intentionally isolated here. Evolution Go's
    public contract is still changing; see docs/PROVIDERS.md before upgrading it.
    """

    webhook_events = ["MESSAGE", "CONNECTION", "QRCODE", "READ_RECEIPT"]
    default_timeout = httpx.Timeout(12.0, connect=5.0)
    profile_timeout = httpx.Timeout(6.0, connect=3.0)

    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        webhook_base_url: str | None = None,
    ) -> None:
        self.base_url = (base_url or settings.evolution_go_base_url).rstrip("/")
        self.api_key = api_key if api_key is not None else settings.evolution_go_api_key
        self.webhook_base_url = (
            webhook_base_url or settings.evolution_go_webhook_base_url
        ).rstrip("/")

    @property
    def headers(self) -> dict[str, str]:
        # Never log this dictionary: it contains the gateway credential.
        return {"apikey": self.api_key, "Content-Type": "application/json"}

    @property
    def _circuit_key(self) -> str:
        return self.base_url

    async def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        timeout = kwargs.pop("timeout", self.default_timeout)
        try:
            async with httpx.AsyncClient(
                base_url=self.base_url, timeout=timeout
            ) as client:
                response = await client.request(
                    method, path, headers=self.headers, **kwargs
                )
        except httpx.HTTPError:
            evolution_circuit.record_failure(self._circuit_key)
            raise
        if response.status_code < 500:
            evolution_circuit.record_success(self._circuit_key)
        else:
            evolution_circuit.record_failure(self._circuit_key)
        return response

    async def send_text(
        self,
        channel: WhatsAppChannel,
        to: str,
        text: str,
        *,
        reply_to_provider_message_id: str | None = None,
        reply_to_participant: str | None = None,
        mentioned_phones: list[str] | None = None,
        mentioned_jids: list[str] | None = None,
        idempotency_key: str | None = None,
    ) -> SendResult:
        try:
            request_payload: dict[str, Any] = {"number": to, "text": text}
            mention_targets = self._mentioned_jids(mentioned_phones, mentioned_jids)
            if mention_targets:
                request_payload["mentionedJid"] = mention_targets
            if idempotency_key:
                request_payload["id"] = idempotency_key
            if reply_to_provider_message_id and reply_to_participant:
                request_payload["quoted"] = {
                    "messageId": reply_to_provider_message_id,
                    "participant": self._as_jid(reply_to_participant),
                }
            response = await self._request(
                "POST",
                "/send/text",
                json=request_payload,
            )
            response.raise_for_status()
            data = response.json()
            message_id = self._message_id(data)
            if not message_id:
                return SendResult(success=False, error="Provider não confirmou o ID da mensagem")
            return SendResult(
                success=True, provider_message_id=message_id, status=MessageStatus.SENT
            )
        except httpx.HTTPError as exc:
            return self._send_error_result(exc)
        except (ValueError, KeyError):
            return SendResult(
                success=False,
                status=MessageStatus.FAILED,
                error="Evolution Go retornou uma confirmação de texto inválida.",
            )

    async def send_media(
        self,
        channel: WhatsAppChannel,
        to: str,
        file_url: str,
        caption: str | None = None,
        *,
        reply_to_provider_message_id: str | None = None,
        reply_to_participant: str | None = None,
        mentioned_phones: list[str] | None = None,
        mentioned_jids: list[str] | None = None,
        idempotency_key: str | None = None,
    ) -> SendResult:
        try:
            provider_url = self._provider_file_url(file_url)
            media_type = self._media_type(file_url)
            if media_type == "sticker":
                path = "/send/sticker"
                request_payload = {"number": to, "sticker": provider_url}
            else:
                path = "/send/media"
                request_payload = {
                    "number": to,
                    "url": provider_url,
                    "caption": caption,
                    "filename": file_url.rsplit("/", 1)[-1].split("?", 1)[0],
                    "type": media_type,
                }
            mention_targets = self._mentioned_jids(mentioned_phones, mentioned_jids)
            if mention_targets:
                request_payload["mentionedJid"] = mention_targets
            if idempotency_key:
                request_payload["id"] = idempotency_key
            if reply_to_provider_message_id and reply_to_participant:
                request_payload["quoted"] = {
                    "messageId": reply_to_provider_message_id,
                    "participant": self._as_jid(reply_to_participant),
                }
            response = await self._request(
                "POST",
                path,
                json=request_payload,
            )
            response.raise_for_status()
            data = response.json()
            message_id = self._message_id(data)
            if not message_id:
                return SendResult(success=False, error="Provider não confirmou o ID da mensagem")
            return SendResult(
                success=True, provider_message_id=message_id, status=MessageStatus.SENT
            )
        except httpx.HTTPError as exc:
            return self._send_error_result(exc)
        except (ValueError, KeyError):
            return SendResult(
                success=False,
                status=MessageStatus.FAILED,
                error="Evolution Go retornou uma confirmação de mídia inválida.",
            )

    async def get_status(self, channel: WhatsAppChannel) -> ChannelStatusResult:
        try:
            response = await self._request("GET", "/instance/status")
            response.raise_for_status()
            return self._parse_status(response.json())
        except httpx.HTTPStatusError as exc:
            return ChannelStatusResult(
                status=ChannelStatus.FAILED,
                error=self._http_error_message(exc),
            )
        except (httpx.HTTPError, ValueError, KeyError) as exc:
            return ChannelStatusResult(status=ChannelStatus.FAILED, error=str(exc))

    async def get_qr_code(self, channel: WhatsAppChannel) -> QRCodeResult:
        try:
            await self._configure_webhook(channel)
            response = await self._request("GET", "/instance/qr")
            response.raise_for_status()
            return self._parse_qr_code(response.json())
        except httpx.HTTPStatusError as exc:
            if self._qr_session_already_connected(exc.response):
                return QRCodeResult(status=ChannelStatus.CONNECTED)
            return QRCodeResult(
                status=ChannelStatus.FAILED,
                error=self._http_error_message(exc),
            )
        except (httpx.HTTPError, ValueError, KeyError) as exc:
            return QRCodeResult(status=ChannelStatus.FAILED, error=str(exc))

    async def _configure_webhook(self, channel: WhatsAppChannel) -> None:
        provider_name = (
            channel.provider.value
            if isinstance(channel.provider, ChannelProvider)
            else str(channel.provider)
        )
        webhook_url = (
            f"{self.webhook_base_url}{settings.api_v1_prefix}/webhooks/whatsapp/"
            f"{provider_name}/{channel.id}"
        )
        response = await self._request(
            "POST",
            "/instance/connect",
            json={
                "webhookUrl": webhook_url,
                "subscribe": self.webhook_events,
                "rabbitmqEnable": "",
                "websocketEnable": "",
                "natsEnable": "",
            },
        )
        response.raise_for_status()

    async def get_contact_profile(
        self, channel: WhatsAppChannel, phone_number: str
    ) -> ContactProfileResult:
        requests = (
            self._profile_request(
                "/user/check",
                {"number": [phone_number], "formatJid": False},
            ),
            self._profile_request("/user/info", {"number": [phone_number]}),
            self._profile_request(
                "/user/avatar",
                {"number": phone_number, "preview": True},
            ),
            self._profile_request("/user/contacts"),
        )
        check, info, avatar, contacts = await asyncio.gather(*requests)
        result = self._parse_contact_profile(
            phone_number=phone_number,
            check=check,
            info=info,
            avatar=avatar,
            contacts=contacts,
        )
        unavailable = sum(value is None for value in (check, info, avatar, contacts))
        if unavailable:
            result.error = (
                "Alguns dados não foram disponibilizados pelo WhatsApp."
                if unavailable < 4
                else "Não foi possível consultar o perfil no WhatsApp."
            )
        return result

    async def get_group_profile(
        self, channel: WhatsAppChannel, group_address: str
    ) -> ContactProfileResult:
        group_jid = self._group_jid(group_address)
        info, avatar = await asyncio.gather(
            self._profile_request("/group/info", {"groupJid": group_jid}),
            self._profile_request(
                "/user/avatar",
                {"number": group_jid, "preview": True},
            ),
        )
        result = self._parse_group_profile(info=info, avatar=avatar)
        if info is None and avatar is None:
            result.error = "Não foi possível consultar o grupo no WhatsApp."
        elif info is None:
            result.error = "Alguns dados do grupo não foram disponibilizados pelo WhatsApp."
        return result

    async def list_groups(self, channel: WhatsAppChannel) -> list[GroupDirectoryEntry]:
        payload = await self._profile_request("/group/myall")
        if payload is None:
            payload = await self._profile_request("/group/list")
        if payload is None:
            return []
        return self._parse_group_directory(payload)

    async def _profile_request(
        self, path: str, payload: dict[str, Any] | None = None
    ) -> dict[str, Any] | None:
        if not evolution_circuit.allow(self._circuit_key):
            return None
        try:
            response = await self._request(
                "POST" if payload is not None else "GET",
                path,
                json=payload,
                timeout=self.profile_timeout,
            )
            response.raise_for_status()
            data = response.json()
            return data if isinstance(data, dict) else None
        except (httpx.HTTPError, ValueError):
            return None

    async def handle_webhook(
        self, payload: dict[str, Any]
    ) -> IncomingMessageResult | IncomingMessageEditResult:
        data = payload.get("data", payload)
        if not isinstance(data, dict):
            raise ValueError("Webhook Evolution Go com data inválido")

        key = self._dict_value(data, "key", "Key")
        info = self._dict_value(data, "info", "Info")
        message = self._dict_value(data, "message", "Message")
        event_type = str(payload.get("event") or payload.get("type") or "").lower()
        is_from_me = self._optional_bool(
            info.get("IsFromMe", info.get("isFromMe"))
        ) is True
        chat_jid = str(info.get("Chat") or info.get("chat") or "")
        is_group = (
            self._optional_bool(info.get("IsGroup", info.get("isGroup"))) is True
            or "@g.us" in chat_jid
        )
        if event_type == "sendmessage":
            raise IgnoredWebhookEvent("Confirmação de envio processada pela chamada da API")
        if event_type and event_type != "message":
            raise IgnoredWebhookEvent(
                f"Evento técnico Evolution Go ignorado: {event_type}"
            )

        message_id = (
            key.get("id")
            or key.get("ID")
            or info.get("ID")
            or info.get("id")
            or data.get("id")
        )
        chat_id, provider_address, participant_phone, from_number = self._chat_identity(
            key,
            info,
            data,
            chat_jid=chat_jid,
            is_group=is_group,
            is_from_me=is_from_me,
        )
        push_name = str(info.get("PushName") or info.get("pushName") or "") or None
        chat_name = self._group_name(info, data) if is_group else None
        raw_timestamp = (
            info.get("Timestamp")
            or info.get("timestamp")
            or data.get("messageTimestamp")
            or data.get("timestamp")
        )

        reaction = self._dict_value(message, "reactionMessage", "ReactionMessage")
        info_type = str(info.get("Type") or info.get("type") or "").lower()
        if reaction or info_type == "reaction":
            raise IgnoredWebhookEvent(
                "Reações não geram mensagens separadas no MVP"
            )

        edit_target, edited_body = self._message_edit(message, info, data)
        if edit_target:
            if not message_id or not from_number:
                raise ValueError("Webhook de edição sem ID ou remetente")
            return IncomingMessageEditResult(
                provider_event_id=str(message_id),
                target_provider_message_id=edit_target,
                from_number=from_number,
                is_group=is_group,
                chat_id=chat_id if is_group else None,
                direction=(
                    MessageDirection.OUTGOING
                    if is_from_me
                    else MessageDirection.INCOMING
                ),
                body=edited_body,
                timestamp=self._timestamp(raw_timestamp),
                raw_payload=payload,
            )

        text = self._message_text(message, data)
        (
            media_type,
            media_url,
            media_base64,
            media_content_type,
            media_file_name,
        ) = self._media(message, data)
        context_info = self._message_context(message)
        reply_to_provider_message_id = (
            context_info.get("stanzaID")
            or context_info.get("StanzaID")
            or context_info.get("stanzaId")
        )
        if not message_id or not from_number:
            raise ValueError("Webhook Evolution Go sem ID ou remetente")
        if media_type is None and not text:
            raise IgnoredWebhookEvent(
                "Mensagem sem conteúdo compatível com o MVP"
            )

        participant_name = None if is_from_me else push_name
        return IncomingMessageResult(
            provider_message_id=str(message_id),
            from_number=from_number,
            to_number=str(data.get("to") or payload.get("instanceId") or ""),
            sender_name=participant_name,
            is_group=is_group,
            chat_id=chat_id if is_group else None,
            chat_name=chat_name,
            provider_address=provider_address if is_group else None,
            participant_phone=participant_phone if is_group else None,
            participant_name=participant_name if is_group else None,
            direction=(
                MessageDirection.OUTGOING if is_from_me else MessageDirection.INCOMING
            ),
            message_type=media_type or MessageType.TEXT,
            body=text,
            media_url=media_url,
            media_base64=media_base64,
            media_content_type=media_content_type,
            media_file_name=media_file_name,
            reply_to_provider_message_id=(
                str(reply_to_provider_message_id) if reply_to_provider_message_id else None
            ),
            timestamp=self._timestamp(raw_timestamp),
            raw_payload=payload,
        )

    def handle_message_status(
        self, payload: dict[str, Any]
    ) -> MessageStatusUpdateResult | None:
        event_type = str(payload.get("event") or payload.get("type") or "").lower()
        if event_type != "receipt":
            return None

        data = payload.get("data", {})
        if not isinstance(data, dict):
            raise ValueError("Recibo Evolution Go com data inválido")

        raw_state = str(
            payload.get("state")
            or data.get("state")
            or data.get("State")
            or data.get("type")
            or data.get("Type")
            or ""
        ).lower()
        if raw_state == "readself":
            raise IgnoredWebhookEvent(
                "ReadSelf confirma leitura local de mensagem recebida, não leitura pelo cliente"
            )
        status_by_state = {
            "delivered": MessageStatus.DELIVERED,
            "read": MessageStatus.READ,
        }
        status = status_by_state.get(raw_state)
        if status is None:
            raise IgnoredWebhookEvent(f"Recibo Evolution Go não suportado: {raw_state or 'vazio'}")

        raw_ids = (
            data.get("MessageIDs")
            or data.get("messageIDs")
            or data.get("messageIds")
            or data.get("message_ids")
            or []
        )
        if isinstance(raw_ids, str):
            raw_ids = [raw_ids]
        if not isinstance(raw_ids, list):
            raise ValueError("Recibo Evolution Go com MessageIDs inválido")
        message_ids = list(dict.fromkeys(str(value) for value in raw_ids if value))
        if not message_ids:
            raise ValueError("Recibo Evolution Go sem MessageIDs")

        raw_timestamp = data.get("Timestamp") or data.get("timestamp")
        return MessageStatusUpdateResult(
            provider_message_ids=message_ids,
            status=status,
            timestamp=self._timestamp(raw_timestamp) if raw_timestamp else None,
        )

    def verify_webhook(
        self,
        payload: dict[str, Any],
        provided_secret: str | None,
        expected_secret: str,
    ) -> bool:
        if super().verify_webhook(payload, provided_secret, expected_secret):
            return True
        instance_token = payload.get("instanceToken")
        return (
            bool(self.api_key)
            and isinstance(instance_token, str)
            and compare_digest(instance_token, self.api_key)
        )

    def sanitize_webhook_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        sanitized = copy.deepcopy(payload)
        sanitized.pop("instanceToken", None)
        data = sanitized.get("data")
        if isinstance(data, dict):
            message = self._dict_value(data, "message", "Message")
            if "base64" in message:
                message.pop("base64", None)
                message["mediaStoredSeparately"] = True
            secret = self._dict_value(
                message, "secretEncryptedMessage", "SecretEncryptedMessage"
            )
            removed_encrypted_payload = False
            for field in ("encIV", "EncIV", "encPayload", "EncPayload"):
                if field in secret:
                    secret.pop(field, None)
                    removed_encrypted_payload = True
            if removed_encrypted_payload:
                secret["encryptedPayloadRemoved"] = True
            context = self._dict_value(
                message, "messageContextInfo", "MessageContextInfo"
            )
            context.pop("deviceListMetadata", None)
            context.pop("DeviceListMetadata", None)
        return sanitized

    def webhook_event_id(self, payload: dict[str, Any]) -> str | None:
        inherited = super().webhook_event_id(payload)
        if inherited:
            return inherited
        if str(payload.get("event") or "").lower() == "receipt":
            try:
                receipt = self.handle_message_status(payload)
            except (IgnoredWebhookEvent, ValueError):
                receipt = None
            if receipt:
                receipt_ids = ",".join(sorted(receipt.provider_message_ids))
                identity = f"{receipt.status.value}:{receipt_ids}"
                return f"receipt:{sha256(identity.encode()).hexdigest()}"
        data = payload.get("data", {})
        if not isinstance(data, dict):
            return None
        info = self._dict_value(data, "info", "Info")
        value = info.get("ID") or info.get("id")
        return str(value) if value else None

    @classmethod
    def _parse_group_profile(
        cls,
        *,
        info: dict[str, Any] | None,
        avatar: dict[str, Any] | None,
    ) -> ContactProfileResult:
        group = cls._group_payload(info)
        members = cls._group_members(group)
        member_count = cls._group_member_count(group, members)
        subject = cls._text_value(
            group,
            "Name",
            "name",
            "Subject",
            "subject",
            "GroupName",
            "groupName",
        )
        about = cls._text_value(
            group,
            "Topic",
            "topic",
            "Description",
            "description",
            "GroupDescription",
            "groupDescription",
        )
        return ContactProfileResult(
            push_name=subject,
            about=about,
            profile_picture_url=cls._avatar_url(avatar),
            is_on_whatsapp=True if group else None,
            group_member_count=member_count,
            group_members=members,
        )

    @classmethod
    def _parse_group_directory(
        cls, payload: dict[str, Any]
    ) -> list[GroupDirectoryEntry]:
        data = cls._response_data(payload)
        items: list[Any]
        if isinstance(data, list):
            items = data
        elif isinstance(data, dict):
            nested = (
                data.get("Groups")
                or data.get("groups")
                or data.get("data")
                or data.get("Data")
            )
            items = nested if isinstance(nested, list) else [data]
        else:
            return []

        entries: list[GroupDirectoryEntry] = []
        seen: set[str] = set()
        for item in items:
            if not isinstance(item, dict):
                continue
            group = cls._group_payload({"data": item}) or item
            jid = str(
                group.get("JID")
                or group.get("Jid")
                or group.get("jid")
                or group.get("GroupJid")
                or group.get("groupJid")
                or group.get("ID")
                or group.get("id")
                or ""
            )
            group_id = cls._number_from_jid(jid)
            if not group_id or group_id in seen:
                continue
            seen.add(group_id)
            provider_address = jid if "@" in jid else f"{group_id}@g.us"
            members = cls._group_members(group)
            member_count = cls._group_member_count(group, members)
            entries.append(
                GroupDirectoryEntry(
                    group_id=group_id,
                    provider_address=provider_address,
                    name=cls._text_value(
                        group,
                        "Name",
                        "name",
                        "Subject",
                        "subject",
                        "GroupName",
                        "groupName",
                    ),
                    about=cls._text_value(
                        group,
                        "Topic",
                        "topic",
                        "Description",
                        "description",
                    ),
                    member_count=member_count,
                    members=members,
                )
            )
        return entries

    @classmethod
    def _group_payload(cls, response: dict[str, Any] | None) -> dict[str, Any]:
        data = cls._response_data(response)
        if isinstance(data, dict):
            nested = data.get("GroupInfo") or data.get("groupInfo") or data.get("Group")
            if isinstance(nested, dict):
                return nested
            return data
        return {}

    @classmethod
    def _group_members(cls, group: dict[str, Any]) -> list[GroupMemberProfile]:
        raw = (
            group.get("Participants")
            or group.get("participants")
            or group.get("Members")
            or group.get("members")
            or []
        )
        if not isinstance(raw, list):
            return []
        members: list[GroupMemberProfile] = []
        seen: set[str] = set()
        for item in raw:
            if not isinstance(item, dict):
                continue
            provider_jid = cls._group_member_jid(item)
            phone = cls._group_member_phone(item, provider_jid)
            member_key = provider_jid or phone
            if not member_key or member_key in seen:
                continue
            seen.add(member_key)
            members.append(
                GroupMemberProfile(
                    phone_number=phone or cls._number_from_jid(provider_jid),
                    provider_jid=provider_jid,
                    name=cls._text_value(
                        item,
                        "DisplayName",
                        "displayName",
                        "PushName",
                        "pushName",
                        "Name",
                        "name",
                    ),
                    is_admin=cls._group_member_is_admin(item),
                )
            )
        return members

    @classmethod
    def _group_member_jid(cls, member: dict[str, Any]) -> str | None:
        jid = cls._text_value(member, "JID", "Jid", "jid")
        if jid:
            return cls._mention_jid(jid)

        lid = cls._text_value(member, "LID", "Lid", "lid")
        if lid:
            return cls._mention_jid(lid)

        raw_id = cls._text_value(member, "ID", "id")
        digits = cls._digits(raw_id or "")
        if len(digits) > 15:
            return f"{digits}@lid"

        return None

    @classmethod
    def _group_member_phone(
        cls,
        member: dict[str, Any],
        provider_jid: str | None,
    ) -> str | None:
        value = cls._text_value(
            member,
            "PhoneNumber",
            "phoneNumber",
            "Phone",
            "phone",
            "Number",
            "number",
        )
        phone = cls._digits(value or "")
        if not phone and provider_jid and provider_jid.endswith("@s.whatsapp.net"):
            phone = cls._number_from_jid(provider_jid)
        return phone if cls._is_mentionable_phone(phone) else None

    @classmethod
    def _group_name(cls, info: dict[str, Any], data: dict[str, Any]) -> str | None:
        group = cls._group_payload(data)
        return (
            cls._text_value(
                info,
                "ChatName",
                "chatName",
                "GroupName",
                "groupName",
                "Subject",
                "subject",
                "Name",
                "name",
            )
            or cls._text_value(
                data,
                "ChatName",
                "chatName",
                "GroupName",
                "groupName",
                "Subject",
                "subject",
                "Name",
                "name",
            )
            or cls._text_value(
                group,
                "Name",
                "name",
                "Subject",
                "subject",
                "GroupName",
                "groupName",
            )
        )

    @classmethod
    def _group_member_count(
        cls,
        group: dict[str, Any],
        members: list[GroupMemberProfile],
    ) -> int | None:
        for key in (
            "ParticipantCount",
            "participantCount",
            "ParticipantsCount",
            "participantsCount",
            "MemberCount",
            "memberCount",
            "MembersCount",
            "membersCount",
            "Size",
            "size",
        ):
            count = cls._optional_int(group.get(key))
            if count is not None:
                return count
        return len(members) or None

    @classmethod
    def _group_member_is_admin(cls, member: dict[str, Any]) -> bool:
        admin_flags = (
            member.get("IsAdmin", member.get("isAdmin")),
            member.get("IsSuperAdmin", member.get("isSuperAdmin")),
        )
        if any(cls._optional_bool(flag) is True for flag in admin_flags):
            return True
        role = cls._text_value(
            member,
            "Role",
            "role",
            "Admin",
            "admin",
            "Type",
            "type",
        )
        return role is not None and role.lower() in {
            "admin",
            "superadmin",
            "super_admin",
            "owner",
        }

    @classmethod
    def _avatar_url(cls, avatar: dict[str, Any] | None) -> str | None:
        avatar_payload = cls._response_data(avatar)
        if not isinstance(avatar_payload, dict):
            return None
        value = avatar_payload.get("URL") or avatar_payload.get("url")
        if isinstance(value, str) and value.startswith(("https://", "http://")):
            return value
        return None

    @classmethod
    def _group_jid(cls, value: str) -> str:
        if "@" in value:
            return value
        digits = cls._digits(value) or value
        return f"{digits}@g.us"

    @classmethod
    def _parse_contact_profile(
        cls,
        *,
        phone_number: str,
        check: dict[str, Any] | None,
        info: dict[str, Any] | None,
        avatar: dict[str, Any] | None,
        contacts: dict[str, Any] | None,
    ) -> ContactProfileResult:
        checked_user = cls._first_user(check)
        info_user = cls._info_user(info, phone_number)
        saved_contact = cls._saved_contact(contacts, phone_number)

        verified_name = cls._verified_name(
            checked_user.get("VerifiedName")
            or checked_user.get("verifiedName")
            or info_user.get("VerifiedName")
            or info_user.get("verifiedName")
        )
        return ContactProfileResult(
            address_book_name=cls._text_value(
                saved_contact,
                "FullName",
                "fullName",
                "FirstName",
                "firstName",
            ),
            push_name=cls._text_value(saved_contact, "PushName", "pushName"),
            business_name=cls._text_value(
                saved_contact, "BusinessName", "businessName"
            ),
            verified_name=verified_name,
            about=cls._text_value(info_user, "Status", "status"),
            profile_picture_url=cls._avatar_url(avatar),
            is_on_whatsapp=cls._optional_bool(
                checked_user.get("IsInWhatsapp", checked_user.get("isInWhatsapp"))
            ),
        )

    @staticmethod
    def _response_data(response: dict[str, Any] | None) -> Any:
        if not isinstance(response, dict):
            return None
        return response.get("data", response)

    @classmethod
    def _first_user(cls, response: dict[str, Any] | None) -> dict[str, Any]:
        data = cls._response_data(response)
        if not isinstance(data, dict):
            return {}
        users = data.get("Users") or data.get("users") or []
        if isinstance(users, list) and users and isinstance(users[0], dict):
            return users[0]
        return {}

    @classmethod
    def _info_user(
        cls, response: dict[str, Any] | None, phone_number: str
    ) -> dict[str, Any]:
        data = cls._response_data(response)
        if not isinstance(data, dict):
            return {}
        users = data.get("Users") or data.get("users") or {}
        if isinstance(users, list):
            return users[0] if users and isinstance(users[0], dict) else {}
        if not isinstance(users, dict):
            return {}
        expected = cls._digits(phone_number)
        for jid, value in users.items():
            if isinstance(value, dict) and cls._digits(str(jid).split("@", 1)[0]) == expected:
                return value
        return next((value for value in users.values() if isinstance(value, dict)), {})

    @classmethod
    def _saved_contact(
        cls, response: dict[str, Any] | None, phone_number: str
    ) -> dict[str, Any]:
        data = cls._response_data(response)
        if not isinstance(data, list):
            return {}
        expected = cls._digits(phone_number)
        for contact in data:
            if not isinstance(contact, dict):
                continue
            jid = str(contact.get("Jid") or contact.get("jid") or "")
            if cls._digits(jid.split("@", 1)[0]) == expected:
                return contact
        return {}

    @classmethod
    def _verified_name(cls, value: Any) -> str | None:
        if isinstance(value, str):
            return value.strip() or None
        if not isinstance(value, dict):
            return None
        details = value.get("details") or value.get("Details") or value
        if not isinstance(details, dict):
            return None
        return cls._text_value(details, "verifiedName", "VerifiedName")

    @staticmethod
    def _text_value(data: dict[str, Any], *keys: str) -> str | None:
        for key in keys:
            value = data.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return None

    @staticmethod
    def _digits(value: str) -> str:
        return "".join(character for character in value if character.isdigit())

    @staticmethod
    def _optional_int(value: Any) -> int | None:
        if isinstance(value, bool):
            return None
        if isinstance(value, int):
            return value if value >= 0 else None
        if isinstance(value, str):
            try:
                parsed = int(value.strip())
            except ValueError:
                return None
            return parsed if parsed >= 0 else None
        return None

    @staticmethod
    def _message_id(data: dict[str, Any]) -> str | None:
        payload = data.get("data", data)
        if not isinstance(payload, dict):
            return None
        info = EvolutionGoProvider._dict_value(payload, "info", "Info")
        key = EvolutionGoProvider._dict_value(payload, "key", "Key")
        value = (
            payload.get("id")
            or payload.get("messageId")
            or info.get("ID")
            or info.get("id")
            or key.get("id")
            or key.get("ID")
        )
        return str(value) if value else None

    @staticmethod
    def _media_type(file_url: str) -> str:
        content_type, _ = mimetypes.guess_type(file_url)
        path = file_url.split("?", 1)[0].lower()
        if content_type == "image/webp" or path.endswith(".webp"):
            return "sticker"
        if content_type and content_type.startswith("image/"):
            return "image"
        if content_type and content_type.startswith("audio/"):
            return "audio"
        if content_type and content_type.startswith("video/"):
            return "video"
        return "document"

    def _provider_file_url(self, file_url: str) -> str:
        public_base = settings.public_api_url.rstrip("/")
        if file_url.startswith(f"{public_base}/"):
            return f"{self.webhook_base_url}{file_url[len(public_base):]}"
        return file_url

    @staticmethod
    def _map_status(raw: str) -> ChannelStatus:
        normalized = raw.lower()
        if normalized in {"connected", "open", "ready"}:
            return ChannelStatus.CONNECTED
        if normalized in {"connecting", "starting"}:
            return ChannelStatus.CONNECTING
        if normalized in {"qrcode", "qr", "requires_qr"}:
            return ChannelStatus.REQUIRES_QR
        if normalized in {"failed", "error"}:
            return ChannelStatus.FAILED
        return ChannelStatus.DISCONNECTED

    @classmethod
    def _parse_status(cls, data: dict[str, Any]) -> ChannelStatusResult:
        """Normalize both Evolution Go 0.7.x and older status envelopes."""
        payload = data.get("data", data)
        if not isinstance(payload, dict):
            raise ValueError("Resposta de status inválida do Evolution Go")

        connected = cls._optional_bool(payload.get("connected", payload.get("Connected")))
        logged_in = cls._optional_bool(
            payload.get(
                "loggedIn",
                payload.get("LoggedIn", payload.get("logged_in")),
            )
        )

        if connected is not None:
            raw = f"connected={str(connected).lower()}"
            if logged_in is not None:
                raw += f",loggedIn={str(logged_in).lower()}"

            if connected and logged_in is not False:
                status = ChannelStatus.CONNECTED
            elif connected and logged_in is False:
                status = ChannelStatus.REQUIRES_QR
            else:
                status = ChannelStatus.DISCONNECTED
            return ChannelStatusResult(status=status, raw_status=raw)

        instance = payload.get("instance", {})
        if not isinstance(instance, dict):
            instance = {}
        raw = str(payload.get("status") or payload.get("state") or instance.get("state") or "")
        return ChannelStatusResult(status=cls._map_status(raw), raw_status=raw)

    @staticmethod
    def _parse_qr_code(data: dict[str, Any]) -> QRCodeResult:
        """Evolution Go 0.7.x wraps QR data in the `data` property."""
        payload = data.get("data", data)
        if not isinstance(payload, dict):
            raise ValueError("Resposta de QR inválida do Evolution Go")
        qr = payload.get("qrcode") or payload.get("qrCode") or payload.get("base64")
        pairing = (
            payload.get("code")
            or payload.get("pairingCode")
            or payload.get("pairing_code")
        )
        return QRCodeResult(
            qr_code=str(qr) if qr else None,
            pairing_code=str(pairing) if pairing else None,
            status=ChannelStatus.REQUIRES_QR if qr or pairing else ChannelStatus.CONNECTING,
        )

    @staticmethod
    def _qr_session_already_connected(response: httpx.Response) -> bool:
        if response.status_code != 400:
            return False
        try:
            data = response.json()
        except ValueError:
            return False
        if not isinstance(data, dict):
            return False
        error = data.get("error")
        return isinstance(error, str) and error.strip().lower() == "session already logged in"

    @staticmethod
    def _optional_bool(value: Any) -> bool | None:
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"true", "1", "yes"}:
                return True
            if normalized in {"false", "0", "no"}:
                return False
        return None

    @staticmethod
    def _http_error_message(exc: httpx.HTTPStatusError) -> str:
        status_code = exc.response.status_code
        if status_code in {401, 403}:
            return (
                "Evolution Go rejeitou o token da instância. "
                "Configure EVOLUTION_GO_API_KEY e reinicie a API."
            )
        return f"Evolution Go respondeu com HTTP {status_code}"

    @classmethod
    def _send_error_result(cls, exc: httpx.HTTPError) -> SendResult:
        if isinstance(
            exc,
            (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout),
        ):
            return SendResult(
                success=False,
                status=MessageStatus.FAILED,
                error="Evolution Go está temporariamente indisponível.",
                retryable=True,
            )
        if isinstance(exc, httpx.HTTPStatusError):
            status_code = exc.response.status_code
            return SendResult(
                success=False,
                status=MessageStatus.FAILED,
                error=cls._http_error_message(exc),
                retryable=status_code == 429,
            )
        if isinstance(
            exc,
            (httpx.ReadTimeout, httpx.WriteTimeout, httpx.RemoteProtocolError),
        ):
            return SendResult(
                success=False,
                status=MessageStatus.FAILED,
                error=(
                    "A resposta do Evolution Go ficou incerta; o reenvio "
                    "automático foi bloqueado."
                ),
            )
        return SendResult(
            success=False,
            status=MessageStatus.FAILED,
            error="Falha segura ao comunicar com o Evolution Go.",
        )

    @classmethod
    def _message_text(
        cls, message: dict[str, Any], data: dict[str, Any] | None = None
    ) -> str | None:
        data = data or {}
        value = (
            message.get("conversation")
            or message.get("Conversation")
            or cls._dict_value(
                message, "extendedTextMessage", "ExtendedTextMessage"
            ).get("text")
            or cls._dict_value(message, "imageMessage", "ImageMessage").get(
                "caption"
            )
            or cls._dict_value(
                message, "documentMessage", "DocumentMessage"
            ).get("caption")
            or cls._dict_value(message, "videoMessage", "VideoMessage").get(
                "caption"
            )
            or data.get("text")
        )
        return str(value) if value is not None else None

    @classmethod
    def _message_edit(
        cls,
        message: dict[str, Any],
        info: dict[str, Any],
        data: dict[str, Any],
    ) -> tuple[str | None, str | None]:
        protocol = cls._dict_value(
            message, "protocolMessage", "ProtocolMessage"
        )
        secret = cls._dict_value(
            message, "secretEncryptedMessage", "SecretEncryptedMessage"
        )
        bot_info = cls._dict_value(info, "MsgBotInfo", "msgBotInfo")
        meta_info = cls._dict_value(info, "MsgMetaInfo", "msgMetaInfo")
        protocol_key = cls._dict_value(protocol, "key", "Key")
        secret_key = cls._dict_value(
            secret, "targetMessageKey", "TargetMessageKey"
        )
        target = (
            bot_info.get("EditTargetID")
            or bot_info.get("editTargetID")
            or meta_info.get("TargetID")
            or meta_info.get("targetID")
            or protocol_key.get("ID")
            or protocol_key.get("id")
            or secret_key.get("ID")
            or secret_key.get("id")
        )
        edit_marker = str(info.get("Edit") or info.get("edit") or "")
        is_edit = (
            edit_marker == "1"
            or cls._optional_bool(data.get("IsEdit", data.get("isEdit"))) is True
            or bool(target and secret)
        )
        if not is_edit or not target:
            return None, None

        edited_message = cls._dict_value(
            protocol, "editedMessage", "EditedMessage"
        )
        if not edited_message:
            edited_message = cls._dict_value(
                message, "editedMessage", "EditedMessage"
            )
        body = cls._message_text(edited_message) if edited_message else None
        if body is None and not secret:
            body = cls._message_text(message, data)
        return str(target), body

    @staticmethod
    def _media(
        message: dict[str, Any], data: dict[str, Any]
    ) -> tuple[MessageType | None, str | None, str | None, str | None, str | None]:
        mapping = (
            (("imageMessage", "ImageMessage"), MessageType.IMAGE),
            (("documentMessage", "DocumentMessage"), MessageType.DOCUMENT),
            (("audioMessage", "AudioMessage"), MessageType.AUDIO),
            (("videoMessage", "VideoMessage"), MessageType.VIDEO),
            (("stickerMessage", "StickerMessage"), MessageType.STICKER),
        )
        for keys, message_type in mapping:
            media = EvolutionGoProvider._dict_value(message, *keys)
            if media:
                return EvolutionGoProvider._media_values(
                    message, data, media, message_type
                )
        document_wrapper = EvolutionGoProvider._dict_value(
            message, "documentWithCaptionMessage", "DocumentWithCaptionMessage"
        )
        wrapped_message = EvolutionGoProvider._dict_value(
            document_wrapper, "message", "Message"
        )
        document = EvolutionGoProvider._dict_value(
            wrapped_message, "documentMessage", "DocumentMessage"
        )
        if document:
            return EvolutionGoProvider._media_values(
                message, data, document, MessageType.DOCUMENT
            )
        return None, None, None, None, None

    @staticmethod
    def _media_values(
        message: dict[str, Any],
        data: dict[str, Any],
        media: dict[str, Any],
        message_type: MessageType,
    ) -> tuple[MessageType, str | None, str | None, str | None, str | None]:
        return (
            message_type,
            media.get("url")
            or media.get("URL")
            or data.get("mediaUrl")
            or data.get("mediaURL"),
            message.get("base64") or message.get("Base64") or data.get("base64"),
            media.get("mimetype") or media.get("Mimetype") or media.get("mimeType"),
            media.get("fileName")
            or media.get("FileName")
            or media.get("filename")
            or media.get("title"),
        )

    @classmethod
    def _message_context(cls, message: dict[str, Any]) -> dict[str, Any]:
        message_keys = (
            ("extendedTextMessage", "ExtendedTextMessage"),
            ("imageMessage", "ImageMessage"),
            ("documentMessage", "DocumentMessage"),
            ("audioMessage", "AudioMessage"),
            ("videoMessage", "VideoMessage"),
            ("stickerMessage", "StickerMessage"),
        )
        for keys in message_keys:
            content = cls._dict_value(message, *keys)
            context = cls._dict_value(content, "contextInfo", "ContextInfo")
            if context:
                return context
        document_wrapper = cls._dict_value(
            message, "documentWithCaptionMessage", "DocumentWithCaptionMessage"
        )
        wrapped_message = cls._dict_value(document_wrapper, "message", "Message")
        document = cls._dict_value(wrapped_message, "documentMessage", "DocumentMessage")
        return cls._dict_value(document, "contextInfo", "ContextInfo")

    @staticmethod
    def _dict_value(data: dict[str, Any], *keys: str) -> dict[str, Any]:
        for key in keys:
            value = data.get(key)
            if isinstance(value, dict):
                return value
        return {}

    @classmethod
    def _contact_jid(
        cls,
        key: dict[str, Any],
        info: dict[str, Any],
        data: dict[str, Any],
        *,
        is_from_me: bool,
    ) -> str:
        if is_from_me:
            return str(
                info.get("RecipientAlt")
                or info.get("recipientAlt")
                or info.get("Chat")
                or info.get("chat")
                or key.get("remoteJid")
                or key.get("RemoteJid")
                or ""
            )
        sender = str(info.get("Sender") or info.get("sender") or "")
        sender_alt = str(info.get("SenderAlt") or info.get("senderAlt") or "")
        if "@lid" in sender and "@s.whatsapp.net" in sender_alt:
            sender = sender_alt
        return str(
            sender
            or key.get("remoteJid")
            or key.get("RemoteJid")
            or info.get("Chat")
            or info.get("chat")
            or data.get("from")
            or ""
        )

    @classmethod
    def _participant_jid(
        cls,
        key: dict[str, Any],
        info: dict[str, Any],
        data: dict[str, Any],
        *,
        is_from_me: bool,
    ) -> str:
        if is_from_me:
            return str(
                info.get("SenderAlt")
                or info.get("senderAlt")
                or info.get("Sender")
                or info.get("sender")
                or ""
            )
        return cls._contact_jid(key, info, data, is_from_me=False)

    @classmethod
    def _chat_identity(
        cls,
        key: dict[str, Any],
        info: dict[str, Any],
        data: dict[str, Any],
        *,
        chat_jid: str,
        is_group: bool,
        is_from_me: bool,
    ) -> tuple[str, str | None, str | None, str]:
        if is_group:
            resolved_chat = chat_jid or str(
                info.get("Chat")
                or info.get("chat")
                or key.get("remoteJid")
                or key.get("RemoteJid")
                or ""
            )
            chat_id = cls._number_from_jid(resolved_chat)
            if not chat_id:
                raise ValueError("Webhook Evolution Go de grupo sem Chat")
            provider_address = (
                resolved_chat
                if "@" in resolved_chat
                else f"{chat_id}@g.us"
            )
            participant_jid = cls._participant_jid(
                key, info, data, is_from_me=is_from_me
            )
            participant_phone = cls._phone_from_jid(participant_jid)
            # Thread key is always the group; participant is metadata only.
            return chat_id, provider_address, participant_phone, chat_id

        remote_jid = cls._contact_jid(key, info, data, is_from_me=is_from_me)
        from_number = cls._phone_from_jid(remote_jid) or ""
        return from_number, None, None, from_number

    @staticmethod
    def _number_from_jid(value: str) -> str:
        return value.split("@", 1)[0].split(":", 1)[0]

    @classmethod
    def _phone_from_jid(cls, value: str) -> str | None:
        if "@lid" in value:
            return None
        number = cls._number_from_jid(value)
        return cls._digits(number) or None

    @staticmethod
    def _is_mentionable_phone(value: str | None) -> bool:
        return bool(value and 10 <= len(value) <= 15)

    @classmethod
    def _mention_jid(cls, value: str | None) -> str | None:
        if not value:
            return None
        raw = value.strip()
        lower = raw.lower()
        if lower.endswith("@lid"):
            digits = cls._digits(raw.split("@", 1)[0])
            return f"{digits}@lid" if digits else None
        if lower.endswith("@s.whatsapp.net"):
            digits = cls._digits(raw.split("@", 1)[0])
            return f"{digits}@s.whatsapp.net" if cls._is_mentionable_phone(digits) else None
        digits = cls._digits(raw)
        if cls._is_mentionable_phone(digits):
            return f"{digits}@s.whatsapp.net"
        if len(digits) > 15:
            return f"{digits}@lid"
        return None

    @classmethod
    def _as_jid(cls, value: str) -> str:
        if "@" in value:
            return value
        digits = cls._digits(value)
        if value.endswith("@g.us") or (digits and value.endswith("g.us")):
            return f"{digits}@g.us"
        return f"{digits}@s.whatsapp.net"

    @classmethod
    def _mentioned_jids(
        cls,
        phones: list[str] | None,
        jids: list[str] | None = None,
    ) -> list[str]:
        mentioned: list[str] = []
        seen: set[str] = set()
        for value in jids or []:
            jid = cls._mention_jid(value)
            if not jid or jid in seen:
                continue
            seen.add(jid)
            mentioned.append(jid)
        for value in phones or []:
            jid = cls._mention_jid(value)
            if not jid or jid in seen:
                continue
            seen.add(jid)
            mentioned.append(jid)
        return mentioned

    @staticmethod
    def _timestamp(value: Any) -> datetime:
        if isinstance(value, (int, float)):
            return datetime.fromtimestamp(value, tz=UTC)
        if isinstance(value, str):
            try:
                return datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                pass
        return datetime.now(UTC)
