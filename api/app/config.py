from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Fluvius Core"
    environment: str = "development"
    api_v1_prefix: str = "/api/v1"
    secret_key: str = "change-me-in-development"
    access_token_expire_minutes: int = 480
    database_url: str = "postgresql+psycopg://fluvius:fluvius@postgres:5432/fluvius"
    redis_url: str = "redis://redis:6379/0"
    cors_origins: str = "http://localhost:5173"
    public_api_url: str = "http://localhost:8000"
    local_storage_path: str = "storage"
    evolution_go_base_url: str = "http://evolution-go:8080"
    evolution_go_webhook_base_url: str = "http://api:8000"
    evolution_go_api_key: str = ""
    webhook_secret: str = ""

    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
