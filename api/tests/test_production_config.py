import unittest

from pydantic import ValidationError

from app.config import Settings


class ProductionSettingsTest(unittest.TestCase):
    def valid_settings(self, **overrides) -> dict:
        values = {
            "environment": "production",
            "secret_key": "secret-key-" + "a" * 32,
            "provider_credentials_key": "provider-key-" + "b" * 32,
            "webhook_secret": "webhook-key-" + "c" * 32,
            "evolution_go_global_api_key": "evolution-key-" + "d" * 32,
            "database_url": (
                "postgresql+psycopg://fluvius:secure-production-password@postgres:5432/fluvius"
            ),
            "redis_url": "redis://:secure-production-password@redis:6379/0",
            "cors_origins": "https://fluvius.finderbit.com.br",
            "public_api_url": "https://fluvius.finderbit.com.br",
            "local_storage_path": "/app/storage",
            "auth_cookie_secure": True,
            "login_rate_limit_enabled": True,
        }
        values.update(overrides)
        return values

    def test_accepts_the_production_contract(self) -> None:
        settings = Settings(_env_file=None, **self.valid_settings())
        self.assertEqual(settings.environment, "production")

    def test_rejects_weak_secrets_and_insecure_urls(self) -> None:
        with self.assertRaises(ValidationError) as raised:
            Settings(
                _env_file=None,
                **self.valid_settings(
                    secret_key="short",
                    public_api_url="http://fluvius.finderbit.com.br",
                    cors_origins="http://localhost:5173",
                    auth_cookie_secure=False,
                    login_rate_limit_enabled=False,
                    local_storage_path="storage",
                ),
            )
        message = str(raised.exception)
        self.assertIn("SECRET_KEY", message)
        self.assertIn("PUBLIC_API_URL", message)
        self.assertIn("AUTH_COOKIE_SECURE", message)

    def test_rejects_reused_production_secrets(self) -> None:
        reused = "same-secret-" + "x" * 32
        with self.assertRaises(ValidationError) as raised:
            Settings(
                _env_file=None,
                **self.valid_settings(
                    secret_key=reused,
                    provider_credentials_key=reused,
                ),
            )
        self.assertIn("independente", str(raised.exception))
