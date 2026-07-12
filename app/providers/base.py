"""Provider interface — abstract contract for all LLM backends."""

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class ChatMessage:
    """One message in a chat conversation."""

    role: str  # "system", "user", or "assistant"
    content: str


@dataclass(frozen=True)
class CompletionRequest:
    """Input for a non-streaming chat completion."""

    model: str
    messages: list[ChatMessage]
    temperature: float | None = None
    max_tokens: int | None = None


@dataclass(frozen=True)
class CompletionResponse:
    """Normalized response from any provider."""

    id: str
    model: str
    content: str
    finish_reason: str | None
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


class LLMProvider(ABC):
    """Abstract base class every LLM provider must implement."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Short provider identifier, e.g. 'openai'."""

    @abstractmethod
    async def complete(self, request: CompletionRequest) -> CompletionResponse:
        """Send a non-streaming completion request and return the full response."""
