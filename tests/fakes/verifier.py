"""Deterministic answer-equivalence verifier for cache integration tests."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class DeterministicVerifier:
    """Cluster-aware verifier double — no OpenAI calls."""

    calls: list[dict[str, str]] = field(default_factory=list)
    forced_result: bool | None = None
    fail_open: bool = False
    malformed: bool = False
    timeout: bool = False

    _POSITIVE_CLUSTERS: tuple[frozenset[str], ...] = (
        frozenset({"france", "capital", "paris"}),
        frozenset({"https", "http", "ssl", "tls"}),
        frozenset({"decorator", "decorators"}),
        frozenset({"wifi", "wi-fi", "wireless", "networking"}),
    )

    async def should_reuse(
        self,
        *,
        cached_request: str,
        cached_response: str,
        new_request: str,
    ) -> bool | None:
        self.calls.append(
            {
                "cached_request": cached_request,
                "cached_response": cached_response,
                "new_request": new_request,
            }
        )
        if self.timeout or self.fail_open:
            return None
        if self.malformed:
            return None
        if self.forced_result is not None:
            return self.forced_result

        cached_l = cached_request.lower()
        new_l = new_request.lower()

        if "oauth" in cached_l and "authentication" in cached_l and "authorization" in new_l:
            return False
        if "list.append" in cached_l or "append" in cached_l:
            if "extend" in new_l:
                return False
        if "sort" in cached_l and "reverse" in new_l:
            return False
        if "type 1" in cached_l and "type 2" in new_l:
            return False
        if "type 1" in cached_l and "type 2 diabetes" in new_l:
            return False

        cached_cluster = self._cluster_index(cached_l)
        new_cluster = self._cluster_index(new_l)
        if cached_cluster is not None and cached_cluster == new_cluster:
            return True
        return False

    def _cluster_index(self, text: str) -> int | None:
        for index, cluster in enumerate(self._POSITIVE_CLUSTERS):
            if any(keyword in text for keyword in cluster):
                return index
        return None


def create_malformed_verifier() -> DeterministicVerifier:
    verifier = DeterministicVerifier()
    verifier.malformed = True
    return verifier
