"""In-memory semantic cache — cosine similarity lookup per project and model."""

from __future__ import annotations

from uuid import UUID

from app.cache.similarity import cosine_similarity
from app.cache.types import CacheEntry, CacheLookupResult, new_cache_entry


class InMemorySemanticCache:
    """Process-local cache backed by PostgreSQL persistence on store/hydrate."""

    def __init__(self, similarity_threshold: float) -> None:
        if not 0.0 <= similarity_threshold <= 1.0:
            raise ValueError("similarity_threshold must be between 0.0 and 1.0")
        self._threshold = similarity_threshold
        self._entries: list[CacheEntry] = []

    @property
    def similarity_threshold(self) -> float:
        return self._threshold

    @property
    def size(self) -> int:
        return len(self._entries)

    def has_entries(self, project_id: UUID, model: str) -> bool:
        """Return True when lookup could match an existing entry."""
        return any(
            entry.project_id == project_id and entry.model == model for entry in self._entries
        )

    def load_entry(self, entry: CacheEntry) -> None:
        """Load one entry from the database without persisting again."""
        self._entries.append(entry)

    def lookup(
        self,
        project_id: UUID,
        model: str,
        embedding: list[float],
    ) -> CacheLookupResult | None:
        """Return the best matching cached response above the threshold, if any."""
        best_entry: CacheEntry | None = None
        best_similarity = -1.0

        for entry in self._entries:
            if entry.project_id != project_id or entry.model != model:
                continue

            if len(entry.embedding) != len(embedding):
                continue

            similarity = cosine_similarity(embedding, entry.embedding)
            if similarity > best_similarity:
                best_similarity = similarity
                best_entry = entry

        if best_entry is None or best_similarity < self._threshold:
            return None

        return CacheLookupResult(
            response=best_entry.response,
            similarity=best_similarity,
            entry_id=best_entry.entry_id,
        )

    def store(
        self,
        project_id: UUID,
        model: str,
        embedding: list[float],
        response: str,
        *,
        entry_id: UUID | None = None,
    ) -> CacheEntry:
        """Append a new in-memory cache entry."""
        entry = new_cache_entry(
            project_id,
            model,
            embedding,
            response,
            entry_id=entry_id,
        )
        self._entries.append(entry)
        return entry

    def clear(self) -> None:
        """Remove all entries (used in tests)."""
        self._entries.clear()
