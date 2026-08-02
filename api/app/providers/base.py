from abc import ABC, abstractmethod
from datetime import datetime
from secrets import compare_digest
from typing import Any

from pydantic import BaseModel, Field

from app.channels.models import WhatsAppChannel
from app.common.enums import ChannelStatus, MessageDirection, MessageStatus, MessageType


class SendResult(BaseModel):
    success: bool
    provider_message_id: str | None = None
    status: MessageStatus = MessageStatus.FAILED
    error: str | None = None
    retryable: bool = False


class ChannelStatusResult(BaseModel):
    status: ChannelStatus
    raw_status: str | None = None
    error: str | None = None


class QRCodeResult(BaseModel):
    qr_code: str | None = None
    pairing_code: str | None = None
    status: ChannelStatus
    error: str | None = None


class IncomingMessageResult(BaseModel):
    provider_message_id: str
    from_number: str
    to_number: str
    sender_name: str | None = None
    is_group: bool = False
    chat_id: str | None = None
    chat_name: str | None = None
    provider_address: str | None = None
    participant_phone: str | None = None
    participant_name: str | None = None
    direction: MessageDirection = MessageDirection.INCOMING
    message_type: MessageType
    body: str | None = None
    media_url: str | None = None
    media_base64: str | None = None
    media_content_type: str | None = None
    media_file_name: str | None = None
    reply_to_provider_message_id: str | None = None
    timestamp: datetime
    raw_payload: dict[str, Any] = Field(default_factory=dict)


class IncomingMessageEditResult(BaseModel):
    provider_event_id: str
    target_provider_message_id: str
    from_number: str
    is_group: bool = False
    chat_id: str | None = None
    direction: MessageDirection = MessageDirection.INCOMING
    body: str | None = None
    timestamp: datetime
    raw_payload: dict[str, Any] = Field(default_factory=dict)


class MessageStatusUpdateResult(BaseModel):
    provider_message_ids: list[str]
    status: MessageStatus
    timestamp: datetime | None = None


class GroupMemberProfile(BaseModel):
    phone_number: str
    provider_jid: str | None = None
    name: str | None = None
    is_admin: bool = False


class ContactProfileResult(BaseModel):
    address_book_name: str | None = None
    push_name: str | None = None
    business_name: str | None = None
    verified_name: str | None = None
    about: str | None = None
    profile_picture_url: str | None = None
    is_on_whatsapp: bool | None = None
    group_member_count: int | None = None
    group_members: list[GroupMemberProfile] = Field(default_factory=list)
    error: str | None = None


class GroupDirectoryEntry(BaseModel):
    group_id: str
    provider_address: str
    name: str | None = None
    about: str | None = None
    profile_picture_url: str | None = None
    member_count: int | None = None
    members: list[GroupMemberProfile] = Field(default_factory=list)


class IgnoredWebhookEvent(ValueError):
    """A valid provider event that does not represent an incoming customer message."""


class WhatsAppProvider(ABC):
    def verify_webhook(
        self,
        payload: dict[str, Any],
        provided_secret: str | None,
        expected_secret: str,
    ) -> bool:
        """Validate the shared Fluvius webhook secret for generic providers."""
        if not expected_secret:
            return True
        return bool(provided_secret) and compare_digest(provided_secret, expected_secret)

    def sanitize_webhook_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        return payload.copy()

    def webhook_event_id(self, payload: dict[str, Any]) -> str | None:
        value = payload.get("event_id") or payload.get("id")
        return str(value) if value else None

    def handle_message_status(
        self, payload: dict[str, Any]
    ) -> MessageStatusUpdateResult | None:
        """Normalize a provider receipt when the adapter supports it."""
        return None

    async def get_contact_profile(
        self, channel: WhatsAppChannel, phone_number: str
    ) -> ContactProfileResult:
        raise NotImplementedError("Consulta de perfil não implementada para este provider")

    async def get_group_profile(
        self, channel: WhatsAppChannel, group_address: str
    ) -> ContactProfileResult:
        raise NotImplementedError("Consulta de grupo não implementada para este provider")

    async def list_groups(self, channel: WhatsAppChannel) -> list[GroupDirectoryEntry]:
        raise NotImplementedError("Listagem de grupos não implementada para este provider")

    @abstractmethod
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
        raise NotImplementedError

    @abstractmethod
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
        raise NotImplementedError

    @abstractmethod
    async def get_status(self, channel: WhatsAppChannel) -> ChannelStatusResult:
        raise NotImplementedError

    @abstractmethod
    async def get_qr_code(self, channel: WhatsAppChannel) -> QRCodeResult:
        raise NotImplementedError

    @abstractmethod
    async def handle_webhook(
        self, payload: dict[str, Any]
    ) -> IncomingMessageResult | IncomingMessageEditResult:
        raise NotImplementedError
