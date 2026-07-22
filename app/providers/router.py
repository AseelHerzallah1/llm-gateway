"""Route models to the correct LLM provider."""

from __future__ import annotations

import logging

from app.config import settings
from app.errors import invalid_request_error
from app.providers.anthropic import create_anthropic_provider
from app.providers.base import LLMProvider
from app.providers.groq import create_groq_provider
from app.providers.openai import OpenAIProvider, create_openai_provider

logger = logging.getLogger(__name__)

GROQ_MODEL_PREFIXES = ("llama", "mixtral", "gemma", "qwen")
OPENAI_MODEL_PREFIXES = ("gpt", "o1", "o3", "o4")


def resolve_provider_name(model: str) -> str:
    """Map a model id to a provider name."""
    lower = model.lower()

    if lower.startswith("claude"):
        return "anthropic"
    if lower.startswith(GROQ_MODEL_PREFIXES):
        return "groq"
    if lower.startswith(OPENAI_MODEL_PREFIXES):
        return "openai"

    raise ValueError(f"No provider routing rule for model '{model}'")


class ProviderRouter:
    """Select a provider implementation based on the requested model."""

    def __init__(self, providers: dict[str, LLMProvider]) -> None:
        if "openai" not in providers:
            raise ValueError("OpenAI provider is required")
        self._providers = providers

    @property
    def provider_names(self) -> list[str]:
        return sorted(self._providers.keys())

    def get_provider(self, model: str) -> LLMProvider:
        try:
            provider_name = resolve_provider_name(model)
        except ValueError as exc:
            raise invalid_request_error(str(exc)) from exc

        provider = self._providers.get(provider_name)
        if provider is None:
            raise invalid_request_error(
                f"Provider '{provider_name}' is not configured for model '{model}'."
            )

        logger.info("Routing model=%s to provider=%s", model, provider.name)
        return provider

    async def aclose(self) -> None:
        closed: set[int] = set()
        for provider in self._providers.values():
            provider_id = id(provider)
            if provider_id in closed:
                continue
            closed.add(provider_id)
            await provider.aclose()


def create_provider_router() -> ProviderRouter:
    """Build the router with all configured providers."""
    providers: dict[str, LLMProvider] = {
        "openai": create_openai_provider(),
    }

    if settings.groq_api_key.get_secret_value():
        providers["groq"] = create_groq_provider()

    if settings.anthropic_api_key.get_secret_value():
        providers["anthropic"] = create_anthropic_provider()

    return ProviderRouter(providers)
