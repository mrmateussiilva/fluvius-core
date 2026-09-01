import json
import unittest
from pathlib import Path
from uuid import uuid4

import httpx

from app.channels.models import WhatsAppChannel
from app.common.enums import ChannelProvider, ChannelStatus
from app.providers.evolution_certification import certify_evolution_go
from app.providers.evolution_contract import (
    EVOLUTION_GO_CONTRACT,
    EVOLUTION_GO_IMAGE_VERSION,
    EVOLUTION_GO_SOURCE_REF,
    EVOLUTION_GO_VERSION,
    EvolutionRoute,
    contract_for,
)
from app.providers.evolution_go import EvolutionGoProvider

API_ROOT = Path(__file__).parents[1]
CONTRACT_FIXTURE = (
    Path(__file__).parent
    / "fixtures"
    / "evolution_go"
    / EVOLUTION_GO_VERSION
    / "swagger-contract.json"
)


def channel() -> WhatsAppChannel:
    return WhatsAppChannel(
        id=uuid4(),
        tenant_id=uuid4(),
        name="Contract test",
        provider=ChannelProvider.EVOLUTION_GO,
        status=ChannelStatus.CONNECTED,
        provider_config={"instance_name": "contract-test"},
    )


class EvolutionGoContractTest(unittest.IsolatedAsyncioTestCase):
    def test_curated_swagger_snapshot_matches_executable_contract(self) -> None:
        snapshot = json.loads(CONTRACT_FIXTURE.read_text(encoding="utf-8"))

        self.assertEqual(snapshot["version"], EVOLUTION_GO_VERSION)
        self.assertEqual(snapshot["source_ref"], EVOLUTION_GO_SOURCE_REF)
        actual = {
            f"{route.method} {route.path.value}": sorted(route.request_fields)
            for route in EVOLUTION_GO_CONTRACT
        }
        self.assertEqual(snapshot["routes"], actual)

    def test_every_route_is_unique_and_resolvable(self) -> None:
        keys = {(route.method, route.path.value) for route in EVOLUTION_GO_CONTRACT}

        self.assertEqual(len(keys), len(EVOLUTION_GO_CONTRACT))
        for method, path in keys:
            self.assertIsNotNone(contract_for(method, path))

    def test_gateway_pin_and_image_version_match_the_contract(self) -> None:
        gateway_root = API_ROOT / "app/providers/evolution_go_gateway"
        dockerfile = (gateway_root / "Dockerfile").read_text(encoding="utf-8")
        connection_pool_patch = (gateway_root / "connection_pool.patch").read_text(encoding="utf-8")

        self.assertIn(EVOLUTION_GO_SOURCE_REF, dockerfile)
        self.assertIn(
            EVOLUTION_GO_IMAGE_VERSION.replace("0.7.2-", "0.7.2-fluvius-"),
            dockerfile,
        )
        self.assertIn("connection_pool.patch", dockerfile)
        self.assertIn("closeSQLStore", connection_pool_patch)
        self.assertIn("sqlStore.Close()", connection_pool_patch)

    async def test_live_certifier_is_read_only_without_a_recipient(self) -> None:
        requests: list[httpx.Request] = []

        async def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            return httpx.Response(
                200,
                json={"data": {"connected": True, "loggedIn": True}},
            )

        provider = EvolutionGoProvider(
            api_key="test-token",
            transport=httpx.MockTransport(handler),
        )
        report = await certify_evolution_go(provider, channel())

        self.assertTrue(report.success)
        self.assertEqual(
            [request.url.path for request in requests], [EvolutionRoute.INSTANCE_STATUS]
        )
        self.assertNotIn("test-token", json.dumps(report.safe_dict()))

    async def test_live_certifier_proves_duplicate_confirmation_and_media(self) -> None:
        requests: list[httpx.Request] = []

        async def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            if request.url.path == EvolutionRoute.INSTANCE_STATUS:
                return httpx.Response(
                    200,
                    json={"data": {"connected": True, "loggedIn": True}},
                )
            body = json.loads(request.content)
            if request.url.path == EvolutionRoute.SEND_TEXT:
                return httpx.Response(200, json={"id": body["id"]})
            if request.url.path == EvolutionRoute.SEND_MEDIA:
                return httpx.Response(200, json={"data": {"key": {"id": body["id"]}}})
            return httpx.Response(404)

        provider = EvolutionGoProvider(
            api_key="test-token",
            transport=httpx.MockTransport(handler),
        )
        report = await certify_evolution_go(
            provider,
            channel(),
            recipient="5527999999999",
            media_url="https://files.example.test/proof.png",
            verify_idempotency=True,
        )

        self.assertTrue(report.success)
        self.assertEqual(
            [check.name for check in report.checks],
            [
                "instance_status",
                "send_text",
                "send_text_idempotency",
                "send_media",
            ],
        )
        text_requests = [
            json.loads(request.content)
            for request in requests
            if request.url.path == EvolutionRoute.SEND_TEXT
        ]
        self.assertEqual(text_requests[0]["id"], text_requests[1]["id"])
        self.assertNotIn("5527999999999", json.dumps(report.safe_dict()))


if __name__ == "__main__":
    unittest.main()
