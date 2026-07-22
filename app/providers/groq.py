"""Groq provider — OpenAI-compatible API via shared httpx client."""

from app.config import settings
from app.providers.openai import OpenAIProvider


def create_groq_provider() -> OpenAIProvider:
    """Build a Groq provider using the OpenAI-compatible chat completions API."""
    return OpenAIProvider(
        api_key=settings.groq_api_key.get_secret_value(),
        base_url=settings.groq_base_url,
        connect_timeout=settings.groq_connect_timeout_s,
        read_timeout=settings.groq_read_timeout_s,
        stream_idle_timeout=settings.groq_stream_idle_timeout_s,
        write_timeout=settings.groq_write_timeout_s,
        pool_timeout=settings.groq_pool_timeout_s,
        provider_name="groq",
    )
