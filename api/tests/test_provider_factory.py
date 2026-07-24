import unittest
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

from app.channels.schemas import ChannelResponse
from app.common.enums import ChannelProvider, ChannelStatus
from app.config import settings
from app.providers.evolution_credentials import ProviderConfigurationError
from app.providers.evolution_go import EvolutionGoProvider
from app.providers.factory import get_provider


class ProviderFactoryTest(unittest.TestCase):
    def test_channel_response_never_exposes_stored_provider_secrets(self) -> None:
        response = ChannelResponse.model_validate(
            SimpleNamespace(
                id=uuid4(),
                name="Principal",
                phone_number=None,
                provider=ChannelProvider.EVOLUTION_GO,
                status=ChannelStatus.DISCONNECTED,
                provider_config={
                    "instance_name": "support",
                    "api_key": "legacy-secret",
                    "base_url": "https://provider.internal",
                },
            )
        )

        self.assertEqual(
            response.model_dump()["provider_config"],
            {"instance_name": "support"},
        )

    def test_resolves_evolution_token_from_non_secret_instance_reference(self) -> None:
        channel = SimpleNamespace(provider_config={"instance_name": "support"})
        with patch.object(
            settings,
            "evolution_go_instance_tokens",
            {"support": "instance-secret"},
        ):
            provider = get_provider(ChannelProvider.EVOLUTION_GO, channel)

        self.assertIsInstance(provider, EvolutionGoProvider)
        self.assertEqual(provider.api_key, "instance-secret")

    def test_rejects_an_instance_reference_without_server_side_credential(self) -> None:
        channel = SimpleNamespace(provider_config={"instance_name": "unknown"})
        with patch.object(
            settings,
            "evolution_go_instance_tokens",
            {"support": "instance-secret"},
        ):
            with self.assertRaisesRegex(
                ProviderConfigurationError,
                "não está configurada",
            ):
                get_provider(ChannelProvider.EVOLUTION_GO, channel)

    def test_uses_legacy_single_instance_token_when_mapping_is_empty(self) -> None:
        channel = SimpleNamespace(provider_config={"instance_name": "personal"})
        with (
            patch.object(settings, "evolution_go_instance_tokens", {}),
            patch.object(settings, "evolution_go_api_key", "legacy-secret"),
        ):
            provider = get_provider(ChannelProvider.EVOLUTION_GO, channel)

        self.assertEqual(provider.api_key, "legacy-secret")


if __name__ == "__main__":
    unittest.main()
