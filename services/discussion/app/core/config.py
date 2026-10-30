from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


SERVICE_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    APP_ENV: str = "development"

    DATABASE_URL: str

    REDIS_URL: str = "redis://localhost:6380/0"

    IDENTITY_BASE_URL: str = "http://localhost:8000"

    JWT_PUBLIC_KEY_PATH: str = "keys/jwt_public.pem"

    JWT_ISSUER: str = "identity"
    JWT_AUDIENCE: str = "forum"

    STATUS_CACHE_TTL_SECONDS: int = 30

    OUTBOX_RELAY_INTERVAL_MS: int = 200
    OUTBOX_BATCH_SIZE: int = 100
    OUTBOX_RETENTION_DAYS: int = 7

    model_config = SettingsConfigDict(
        env_file=SERVICE_ROOT / ".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()