"""Deterministic embedding provider for cache integration tests."""

from __future__ import annotations


class DeterministicEmbeddingProvider:
    """Map prompt keywords to fixed vectors — no OpenAI calls."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    @property
    def name(self) -> str:
        return "deterministic-embeddings"

    async def embed(self, text: str) -> list[float]:
        self.calls.append(text)
        lowered = text.lower()
        if "paris" in lowered:
            return [1.0, 0.0, 0.0]
        if "london" in lowered:
            return [0.0, 1.0, 0.0]
        return [0.5, 0.5, 0.0]

    async def aclose(self) -> None:
        return None
