"""Gateway cache factory."""

from app.cache.memory import GatewayCache
from app.config import settings


def create_gateway_cache() -> GatewayCache:
    """Build the process-local L1+L2 cache from settings."""
    return GatewayCache(candidate_threshold=settings.cache_candidate_threshold)


create_semantic_cache = create_gateway_cache
