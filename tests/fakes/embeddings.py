"""Deterministic embedding provider for cache integration tests."""

from __future__ import annotations

import math


def _normalize(vector: list[float]) -> list[float]:
    magnitude = math.sqrt(sum(value * value for value in vector))
    if magnitude == 0:
        return vector
    return [value / magnitude for value in vector]


_CLUSTER_VECTORS: dict[str, list[float]] = {
    "france": _normalize([1.0, 0.0, 0.0]),
    "https": _normalize([0.92, 0.38, 0.0]),
    "decorator": _normalize([0.7, 0.71, 0.0]),
    "wifi": _normalize([0.6, 0.8, 0.0]),
    "oauth": _normalize([0.85, 0.53, 0.0]),
    "append": _normalize([0.5, 0.87, 0.0]),
    "sort": _normalize([0.45, 0.89, 0.0]),
    "diabetes": _normalize([0.88, 0.47, 0.0]),
    "london": _normalize([0.0, 1.0, 0.0]),
    "generic": _normalize([0.5, 0.5, 0.0]),
}


def _cluster_for_text(text: str) -> str:
    lowered = text.lower()
    if "london" in lowered:
        return "london"
    if any(keyword in lowered for keyword in ("france", "capital", "paris")):
        return "france"
    if "https" in lowered or "http" in lowered:
        return "https"
    if "decorator" in lowered:
        return "decorator"
    if "wifi" in lowered or "wi-fi" in lowered or "wireless" in lowered:
        return "wifi"
    if "oauth" in lowered:
        return "oauth"
    if "append" in lowered or "extend" in lowered:
        return "append"
    if ("sort" in lowered and "reverse" not in lowered) or "reverse" in lowered:
        return "sort"
    if "diabetes" in lowered:
        return "diabetes"
    return "generic"


class DeterministicEmbeddingProvider:
    """Map prompt keywords to fixed vectors — no OpenAI calls."""

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.fail_next: bool = False

    @property
    def name(self) -> str:
        return "deterministic-embeddings"

    async def embed(self, text: str) -> list[float]:
        if self.fail_next:
            self.fail_next = False
            raise RuntimeError("embedding failed")
        self.calls.append(text)
        cluster = _cluster_for_text(text)
        return list(_CLUSTER_VECTORS[cluster])

    async def aclose(self) -> None:
        return None
