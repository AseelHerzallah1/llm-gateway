"""Application configuration loaded from environment variables."""

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """All gateway settings. Values come from environment variables or a `.env` file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # Application
    app_env: Literal["development", "production", "test"] = "development"
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    log_level: str = "info"

    # Database (used from Phase 2.5+)
    database_url: str = "postgresql+asyncpg://gateway:gateway@localhost:5432/llm_gateway"

    # OpenAI provider (used from Phase 3+)
    openai_api_key: SecretStr = Field(default=SecretStr(""))
    openai_base_url: str = "https://api.openai.com/v1"

    # Security (used from Phase 3+)
    secret_key: SecretStr = Field(default=SecretStr("change-me"))

    # Semantic cache (used from Phase 6+)
    cache_similarity_threshold: float = 0.92


@lru_cache
def get_settings() -> Settings:
    """Return a cached Settings instance (loaded once per process)."""
    return Settings()


settings = get_settings()
