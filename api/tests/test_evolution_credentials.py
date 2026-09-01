import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from app.common.enums import ChannelProvider
from app.providers.evolution_credentials import ensure_evolution_channel_credential


class EvolutionCredentialLookupTest(unittest.TestCase):
    def test_existing_credential_is_read_without_row_lock(self) -> None:
        db = Mock()
        channel = SimpleNamespace(provider=ChannelProvider.EVOLUTION_GO)
        credential = object()

        with patch(
            "app.providers.evolution_credentials.get_channel_credential",
            return_value=credential,
        ) as lookup:
            result = ensure_evolution_channel_credential(db, channel)

        self.assertIs(result, credential)
        lookup.assert_called_once_with(db, channel)


if __name__ == "__main__":
    unittest.main()
