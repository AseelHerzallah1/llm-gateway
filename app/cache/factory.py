"""Semantic cache factory."""

from app.cache.memory import InMemorySemanticCache
from app.config import settings


def create_semantic_cache() -> InMemorySemanticCache:
    """Build the process-local semantic cache from settings."""
    return InMemorySemanticCache(similarity_threshold=settings.cache_similarity_threshold)
