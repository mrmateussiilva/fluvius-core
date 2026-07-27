import json
import unittest

import httpx

from app.providers.evolution_admin import (
    EvolutionGoAdminClient,
    EvolutionGoProvisioningError,
    EvolutionInstance,
)


class EvolutionGoAdminClientTest(unittest.IsolatedAsyncioTestCase):
    async def test_creates_an_instance_with_the_global_key(self) -> None:
        captured: dict[str, object] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["path"] = request.url.path
            captured["api_key"] = request.headers["apikey"]
            captured["payload"] = json.loads(request.content)
            return httpx.Response(200, json={"message": "success"})

        client = EvolutionGoAdminClient(
            base_url="https://evolution.internal",
            global_api_key="global-secret",
            transport=httpx.MockTransport(handler),
        )
        instance = EvolutionInstance(
            instance_id="channel-id",
            name="fluvius-channel",
            token="instance-secret",
        )

        await client.create_instance(instance)

        self.assertEqual(captured["path"], "/instance/create")
        self.assertEqual(captured["api_key"], "global-secret")
        self.assertEqual(
            captured["payload"],
            {
                "instanceId": "channel-id",
                "name": "fluvius-channel",
                "token": "instance-secret",
            },
        )

    async def test_timeout_is_ambiguous_and_never_reported_as_success(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ReadTimeout("timeout", request=request)

        client = EvolutionGoAdminClient(
            base_url="https://evolution.internal",
            global_api_key="global-secret",
            transport=httpx.MockTransport(handler),
        )

        with self.assertRaises(EvolutionGoProvisioningError) as raised:
            await client.create_instance(
                EvolutionInstance(
                    instance_id="channel-id",
                    name="fluvius-channel",
                    token="instance-secret",
                )
            )

        self.assertTrue(raised.exception.ambiguous)
        self.assertNotIn("instance-secret", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
