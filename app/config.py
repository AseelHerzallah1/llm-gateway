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
    openai_connect_timeout_s: float = 10.0
    openai_read_timeout_s: float = 60.0
    openai_stream_idle_timeout_s: float = 30.0
    openai_write_timeout_s: float = 10.0
    openai_pool_timeout_s: float = 10.0
    openai_embedding_model: str = "text-embedding-3-small"

    # Anthropic provider (used from Phase 7+)
    anthropic_api_key: SecretStr = Field(default=SecretStr(""))
    anthropic_base_url: str = "https://api.anthropic.com/v1"
    anthropic_api_version: str = "2023-06-01"
    anthropic_default_max_tokens: int = 1024
    anthropic_connect_timeout_s: float = 10.0
    anthropic_read_timeout_s: float = 60.0
    anthropic_stream_idle_timeout_s: float = 30.0
    anthropic_write_timeout_s: float = 10.0
    anthropic_pool_timeout_s: float = 10.0

    # Security (used from Phase 3+)
    secret_key: SecretStr = Field(default=SecretStr("change-me"))

    # Semantic cache (used from Phase 6+)
    cache_similarity_threshold: float = 0.92


@lru_cache
def get_settings() -> Settings:
    """Return a cached Settings instance (loaded once per process)."""
    return Settings()


settings = get_settings()
