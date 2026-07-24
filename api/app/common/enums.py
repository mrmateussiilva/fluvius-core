from enum import StrEnum


class ChannelProvider(StrEnum):
    EVOLUTION_GO = "evolution_go"
    META_CLOUD = "meta_cloud"
    BSP = "bsp"


class ChannelStatus(StrEnum):
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    REQUIRES_QR = "requires_qr"
    FAILED = "failed"


class ConversationStatus(StrEnum):
    NEW = "new"
    OPEN = "open"
    CLOSED = "closed"


class MessageDirection(StrEnum):
    INCOMING = "incoming"
    OUTGOING = "outgoing"


class MessageType(StrEnum):
    TEXT = "text"
    IMAGE = "image"
    DOCUMENT = "document"
    AUDIO = "audio"
    VIDEO = "video"
    STICKER = "sticker"


class MessageStatus(StrEnum):
    PENDING = "pending"
    SENT = "sent"
    DELIVERED = "delivered"
    READ = "read"
    FAILED = "failed"
