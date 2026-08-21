from typing import Any
import httpx

_client_pool: dict[tuple[str, int | None], httpx.AsyncClient] = {}


def get_evolution_http_client(
    base_url: str,
    transport: httpx.AsyncBaseTransport | None = None,
) -> httpx.AsyncClient:
    key = (base_url.rstrip("/"), id(transport) if transport is not None else None)
    client = _client_pool.get(key)
    if client is None or client.is_closed:
        client = httpx.AsyncClient(
            base_url=base_url,
            transport=transport,
            limits=httpx.Limits(
                max_keepalive_connections=20,
                max_connections=100,
                keepalive_expiry=30.0,
            ),
        )
        _client_pool[key] = client
    return client


async def close_evolution_http_clients() -> None:
    for client in list(_client_pool.values()):
        if not client.is_closed:
            await client.aclose()
    _client_pool.clear()
