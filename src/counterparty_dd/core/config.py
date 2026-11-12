from functools import lru_cache

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="CDD_", env_file=".env", extra="ignore")

    env: str = "development"
    database_url: str = "postgresql+asyncpg://cdd:cdd-local-only@localhost:5455/counterparty_dd"
    redis_url: str = "redis://localhost:6399/0"
    token_secret: SecretStr = Field(min_length=32)
    audit_secret: SecretStr = Field(min_length=32)
    access_ttl_seconds: int = 3600
    refresh_ttl_seconds: int = 7 * 24 * 3600
    login_attempts: int = 5
    login_window_seconds: int = 900
    screening_threshold: float = Field(default=0.75, ge=0.0, le=1.0)
    high_risk_countries: list[str] = Field(default_factory=list)
    cors_origins: list[str] = Field(default_factory=list)


@lru_cache
def get_settings() -> Settings:
    return Settings()
