from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

EVOLUTION_GO_VERSION = "0.7.2"
EVOLUTION_GO_SOURCE_REF = "9337afc47e10b86cc896a6f432240e40fee95dd1"
EVOLUTION_GO_IMAGE_VERSION = "0.7.2-connection-pool-fix.3"
EVOLUTION_GO_CONTRACT_DRIFT_ERROR = "Evento Evolution Go fora do contrato certificado"


class EvolutionRoute(StrEnum):
    INSTANCE_CREATE = "/instance/create"
    INSTANCE_DELETE = "/instance/delete/{instance_id}"
    INSTANCE_CONNECT = "/instance/connect"
    INSTANCE_QR = "/instance/qr"
    INSTANCE_STATUS = "/instance/status"
    SEND_TEXT = "/send/text"
    SEND_MEDIA = "/send/media"
    SEND_STICKER = "/send/sticker"
    SEND_CONTACT = "/send/contact"
    USER_CHECK = "/user/check"
    USER_INFO = "/user/info"
    USER_AVATAR = "/user/avatar"
    USER_CONTACTS = "/user/contacts"
    GROUP_INFO = "/group/info"
    GROUP_MY_ALL = "/group/myall"
    GROUP_LIST = "/group/list"
    HISTORY_SYNC = "/chat/history-sync"


@dataclass(frozen=True, slots=True)
class EvolutionRouteContract:
    method: str
    path: EvolutionRoute
    operation: str
    request_fields: frozenset[str] = frozenset()
    confirmation_fields: frozenset[str] = frozenset()
    critical: bool = False


EVOLUTION_GO_CONTRACT: tuple[EvolutionRouteContract, ...] = (
    EvolutionRouteContract(
        "POST",
        EvolutionRoute.INSTANCE_CREATE,
        "provision instance",
        frozenset({"instanceId", "name", "token"}),
        critical=True,
    ),
    EvolutionRouteContract(
        "DELETE",
        EvolutionRoute.INSTANCE_DELETE,
        "remove instance",
        critical=True,
    ),
    EvolutionRouteContract(
        "POST",
        EvolutionRoute.INSTANCE_CONNECT,
        "configure webhook and connect",
        frozenset({"webhookUrl", "subscribe"}),
        critical=True,
    ),
    EvolutionRouteContract("GET", EvolutionRoute.INSTANCE_QR, "request QR", critical=True),
    EvolutionRouteContract(
        "GET", EvolutionRoute.INSTANCE_STATUS, "read connection status", critical=True
    ),
    EvolutionRouteContract(
        "POST",
        EvolutionRoute.SEND_TEXT,
        "send text",
        frozenset({"number", "text"}),
        frozenset({"id"}),
        critical=True,
    ),
    EvolutionRouteContract(
        "POST",
        EvolutionRoute.SEND_MEDIA,
        "send media",
        frozenset({"number", "url", "type"}),
        frozenset({"id"}),
        critical=True,
    ),
    EvolutionRouteContract(
        "POST",
        EvolutionRoute.SEND_STICKER,
        "send sticker",
        frozenset({"number", "sticker"}),
        frozenset({"id"}),
        critical=True,
    ),
    EvolutionRouteContract(
        "POST",
        EvolutionRoute.SEND_CONTACT,
        "send contact",
        frozenset({"number", "vcard"}),
        frozenset({"id"}),
        critical=True,
    ),
    EvolutionRouteContract(
        "POST", EvolutionRoute.USER_CHECK, "check WhatsApp user", frozenset({"number"})
    ),
    EvolutionRouteContract(
        "POST", EvolutionRoute.USER_INFO, "read user profile", frozenset({"number"})
    ),
    EvolutionRouteContract(
        "POST", EvolutionRoute.USER_AVATAR, "read avatar", frozenset({"number"})
    ),
    EvolutionRouteContract("GET", EvolutionRoute.USER_CONTACTS, "list contacts"),
    EvolutionRouteContract(
        "POST", EvolutionRoute.GROUP_INFO, "read group", frozenset({"groupJid"})
    ),
    EvolutionRouteContract("GET", EvolutionRoute.GROUP_MY_ALL, "list joined groups"),
    EvolutionRouteContract("GET", EvolutionRoute.GROUP_LIST, "list groups fallback"),
    EvolutionRouteContract(
        "POST",
        EvolutionRoute.HISTORY_SYNC,
        "request history sync",
        frozenset({"messageInfo", "count"}),
        critical=True,
    ),
)


def contract_for(method: str, path: str) -> EvolutionRouteContract | None:
    normalized_method = method.upper()
    for route in EVOLUTION_GO_CONTRACT:
        if route.method == normalized_method and route.path.value == path:
            return route
    return None
