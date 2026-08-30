from functools import lru_cache
from urllib.parse import urlparse

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Fluvius Core"
    deployment_slot: str = "legacy"
    environment: str = "development"
    api_v1_prefix: str = "/api/v1"
    secret_key: str = "change-me-in-development"
    access_token_expire_minutes: int = 480
    auth_cookie_name: str = "fluvius_session"
    auth_cookie_secure: bool = False
    login_rate_limit_enabled: bool = False
    login_rate_limit_attempts: int = 10
    login_rate_limit_window_seconds: int = 900
    database_url: str = "postgresql+psycopg://fluvius:fluvius@postgres:5432/fluvius"
    redis_url: str = "redis://redis:6379/0"
    cors_origins: str = "http://localhost:5173"
    public_api_url: str = "http://localhost:8000"
    local_storage_path: str = "storage"
    evolution_go_base_url: str = "http://evolution-go:8080"
    evolution_go_webhook_base_url: str = "http://api:8000"
    evolution_go_api_key: str = ""
    evolution_go_global_api_key: str = ""
    evolution_go_instance_tokens: dict[str, str] = Field(default_factory=dict)
    provider_credentials_key: str = ""
    webhook_secret: str = ""
    history_sync_max_age_days: int = 30

    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @model_validator(mode="after")
    def validate_production_settings(self) -> "Settings":
        if self.environment != "production":
            return self

        errors: list[str] = []
        secrets = {
            "SECRET_KEY": self.secret_key,
            "PROVIDER_CREDENTIALS_KEY": self.provider_credentials_key,
            "WEBHOOK_SECRET": self.webhook_secret,
            "EVOLUTION_GO_GLOBAL_API_KEY": self.evolution_go_global_api_key,
        }
        weak_values = {
            "",
            "change-me",
            "change-me-in-development",
            "local-only-change-me",
            "local-webhook-secret",
            "local-evolution-admin-key",
        }
        for name, value in secrets.items():
            if len(value) < 32 or value in weak_values:
                errors.append(f"{name} deve ter ao menos 32 caracteres aleatórios")
        configured_secrets = [value for value in secrets.values() if value]
        if len(configured_secrets) != len(set(configured_secrets)):
            errors.append("Cada segredo de produção deve possuir um valor independente")

        if urlparse(self.public_api_url).scheme != "https":
            errors.append("PUBLIC_API_URL deve usar HTTPS em produção")
        origins = self.cors_origin_list
        if not origins or any(
            urlparse(origin).scheme != "https" or "localhost" in origin
            for origin in origins
        ):
            errors.append("CORS_ORIGINS deve conter apenas origens HTTPS explícitas")
        if self.public_api_url.rstrip("/") not in {
            origin.rstrip("/") for origin in origins
        }:
            errors.append("PUBLIC_API_URL deve pertencer às origens CORS permitidas")
        if not self.auth_cookie_secure:
            errors.append("AUTH_COOKIE_SECURE deve estar ativo em produção")
        if not self.login_rate_limit_enabled:
            errors.append("LOGIN_RATE_LIMIT_ENABLED deve estar ativo em produção")
        if not self.local_storage_path.startswith("/"):
            errors.append("LOCAL_STORAGE_PATH deve ser absoluto em produção")
        database_password = urlparse(self.database_url).password
        if not database_password or len(database_password) < 16:
            errors.append("DATABASE_URL deve possuir uma senha forte")
        redis_password = urlparse(self.redis_url).password
        if not redis_password or len(redis_password) < 16:
            errors.append("REDIS_URL deve exigir autenticação em produção")

        if errors:
            raise ValueError("Configuração de produção inválida: " + "; ".join(errors))
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
