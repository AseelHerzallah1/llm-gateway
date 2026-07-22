"""Embedding provider interface."""

from abc import ABC, abstractmethod


class EmbeddingProvider(ABC):
    """Compute vector embeddings for semantic cache lookup."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Short provider identifier, e.g. 'openai'."""

    @abstractmethod
    async def embed(self, text: str) -> list[float]:
        """Return an embedding vector for the given text."""

    @abstractmethod
    async def aclose(self) -> None:
        """Release HTTP resources."""
