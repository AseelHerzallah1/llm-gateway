"""Semantic cache — embeddings and similarity lookup (Phase 6+)."""

from app.cache.factory import create_semantic_cache
from app.cache.memory import InMemorySemanticCache
from app.cache.similarity import cosine_similarity
from app.cache.types import CacheLookupResult

__all__ = [
    "CacheLookupResult",
    "InMemorySemanticCache",
    "cosine_similarity",
    "create_semantic_cache",
]
