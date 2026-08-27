"""In-memory gateway cache — L1 exact index + L2 semantic scan."""

from __future__ import annotations

from uuid import UUID

from app.cache.similarity import cosine_similarity
from app.cache.types import CacheEntry, SemanticCandidate, new_cache_entry


class GatewayCache:
    """Process-local cache: O(1) exact lookup + linear semantic candidate retrieval."""

    def __init__(self, candidate_threshold: float) -> None:
        if not 0.0 <= candidate_threshold <= 1.0:
            raise ValueError("candidate_threshold must be between 0.0 and 1.0")
        self._candidate_threshold = candidate_threshold
        self._exact_index: dict[tuple[UUID, str], CacheEntry] = {}
        self._semantic_entries: list[CacheEntry] = []

    @property
    def candidate_threshold(self) -> float:
        return self._candidate_threshold

    @property
    def size(self) -> int:
        return len(self._semantic_entries)

    def has_semantic_entries(self, project_id: UUID, model: str) -> bool:
        return any(
            entry.project_id == project_id and entry.model == model
            for entry in self._semantic_entries
        )

    def lookup_exact(self, project_id: UUID, fingerprint: str) -> CacheEntry | None:
        return self._exact_index.get((project_id, fingerprint))

    def lookup_semantic_candidate(
        self,
        project_id: UUID,
        model: str,
        embedding: list[float],
        *,
        temperature: float | None,
        max_tokens: int | None,
    ) -> SemanticCandidate | None:
        best_entry: CacheEntry | None = None
        best_similarity = -1.0

        for entry in self._semantic_entries:
            if entry.project_id != project_id or entry.model != model:
                continue
            if not entry.request_messages:
                continue
            if entry.temperature != temperature or entry.max_tokens != max_tokens:
                continue
            if len(entry.embedding) != len(embedding):
                continue

            similarity = cosine_similarity(embedding, entry.embedding)
            if similarity > best_similarity:
                best_similarity = similarity
                best_entry = entry

        if best_entry is None or best_similarity < self._candidate_threshold:
            return None

        return SemanticCandidate(entry=best_entry, similarity=best_similarity)

    def load_entry(self, entry: CacheEntry) -> None:
        """Load one entry from persistence without writing back."""
        self._replace_semantic_entry(entry)
        if entry.fingerprint:
            self._exact_index[(entry.project_id, entry.fingerprint)] = entry

    def upsert_entry(self, entry: CacheEntry) -> None:
        """Insert or replace in-memory indexes."""
        self._replace_semantic_entry(entry)
        if entry.fingerprint:
            self._exact_index[(entry.project_id, entry.fingerprint)] = entry

    def _replace_semantic_entry(self, entry: CacheEntry) -> None:
        if entry.entry_id is not None:
            self._semantic_entries = [
                existing
                for existing in self._semantic_entries
                if existing.entry_id != entry.entry_id
            ]
        elif entry.fingerprint:
            self._semantic_entries = [
                existing
                for existing in self._semantic_entries
                if not (
                    existing.project_id == entry.project_id
                    and existing.fingerprint == entry.fingerprint
                )
            ]
        self._semantic_entries.append(entry)

    def store(
        self,
        project_id: UUID,
        model: str,
        embedding: list[float],
        response: str,
        *,
        entry_id: UUID | None = None,
        fingerprint: str | None = None,
        fingerprint_version: int | None = None,
        request_messages: tuple = (),
        temperature: float | None = None,
        max_tokens: int | None = None,
        pii_values_hash: str | None = None,
    ) -> CacheEntry:
        entry = new_cache_entry(
            project_id,
            model,
            embedding,
            response,
            entry_id=entry_id,
            fingerprint=fingerprint,
            fingerprint_version=fingerprint_version,
            request_messages=request_messages,
            temperature=temperature,
            max_tokens=max_tokens,
            pii_values_hash=pii_values_hash,
        )
        self.upsert_entry(entry)
        return entry

    def clear(self) -> None:
        self._exact_index.clear()
        self._semantic_entries.clear()

    def purge_project(self, project_id: UUID) -> int:
        """Remove all in-memory exact + semantic entries for one project."""
        before = len(self._semantic_entries)
        self._semantic_entries = [
            entry for entry in self._semantic_entries if entry.project_id != project_id
        ]
        for key in [key for key in self._exact_index if key[0] == project_id]:
            del self._exact_index[key]
        return before - len(self._semantic_entries)


InMemorySemanticCache = GatewayCache
